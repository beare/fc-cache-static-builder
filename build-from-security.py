#!/usr/bin/python3

import apt
import atexit
import glob
import os
import shutil
import subprocess
import sys
import tempfile

arch_to_base_uri = {
    "amd64": "http://archive.ubuntu.com/ubuntu",
    "i386":  "http://archive.ubuntu.com/ubuntu",
    # ports
    "s390x": "http://ports.ubuntu.com/ubuntu-ports",
    "arm64": "http://ports.ubuntu.com/ubuntu-ports",
    "armhf": "http://ports.ubuntu.com/ubuntu-ports",
    "ppc64el": "http://ports.ubuntu.com/ubuntu-ports",
}

def fetch_source_from_security(release, pkgname):
    with tempfile.TemporaryDirectory(prefix="aptroot-{}".format(release)) as base:
        sources_list = base+"/etc/apt/sources.list"
        os.makedirs(os.path.dirname(sources_list), exist_ok=True)
        base_uri = arch_to_base_uri[apt.apt_pkg.get_architectures()[0]]
        with open(sources_list, "w") as fp:
            fp.write("""
deb {base_uri} {dist} main
deb-src {base_uri} {dist} main
deb {base_uri} {dist}-security main
deb-src {base_uri} {dist}-security main
        """.format(base_uri=base_uri, dist=release))

        # copy keys in place
        shutil.copy2("/etc/apt/trusted.gpg", base+"/etc/apt/trusted.gpg")
        shutil.copytree("/etc/apt/trusted.gpg.d", base+"/etc/apt/trusted.gpg.d")
        # and create/update cache
        cache = apt.Cache(rootdir=base)
        cache.update(apt.progress.text.AcquireProgress())
        cache.open()
        # fetch/extract source (python-apt uses dpkg-source -x interally)
        pkg_src_dir = tempfile.mkdtemp(prefix="{}-{}-src".format(release, pkgname))
        os.makedirs(pkg_src_dir, exist_ok=True)
        pkg = cache[pkgname]
        if not glob.glob("{}/{}-*".format(pkg_src_dir, pkgname)):
            pkg.candidate.fetch_source(destdir=pkg_src_dir)
    return pkg_src_dir


def cleanup_self_build_fontconfig():
    with tempfile.TemporaryDirectory(prefix="freetype-cleanup") as tmp:
        subprocess.check_call("sudo", "apt-get", "remove", "-y", "libfreetype6-dev", cwd=tmp)
        subprocess.check_call("sudo", "apt-get", "download", "libfreetype6", cwd=tmp)
        subprocess.check_call("sudo", "dpkg", "-i", "./libfreetype6_*.deb", cwd=tmp)


def build_freetype(release):
    pkgbasesrcdir = fetch_source_from_security(release, "libfreetype6-dev")
    atexit.register(shutil.rmtree, pkgbasesrcdir)
    pkgsrcdir = glob.glob(pkgbasesrcdir+"/freetype-*")[0]
    # XXX: apply any patches
    subprocess.check_call(["sudo", "apt-get", "-y", "build-dep", pkgsrcdir])
    subprocess.check_call(["dpkg-buildpackage", "-uc", "-us", "-Zgzip"], cwd=pkgsrcdir)
    # exclude "freetype2-demos" from the installed debs
    debs = glob.glob(pkgbasesrcdir+"/libfreetype*.deb")
    subprocess.check_call(["sudo", "apt-get", "install", "-y", "--allow-downgrades"]+debs)
    # ensure we cleanup our self-installed stuff
    atexit.register(cleanup_self_build_fontconfig)


def build_fontconfig(release):
    pkgbasesrcdir = fetch_source_from_security(release, "fontconfig")
    atexit.register(shutil.rmtree, pkgbasesrcdir)
    pkgsrcdir = glob.glob(pkgbasesrcdir+"/fontconfig-*")[0]
    # apply any build fixes
    for p in glob.glob("patches/{}/*.patch".format(release)):
        print("applying {}".format(p))
        if not os.path.exists(pkgsrcdir+"/debian/patches/"+p):
            shutil.copy(p, os.path.join(pkgsrcdir, "debian", "patches"))
            subprocess.call("echo {} >> {}/debian/patches/series".format(os.path.basename(p), pkgsrcdir), shell=True)
    # do the normal build first
    subprocess.check_call(["sudo", "apt-get", "-y", "build-dep", pkgsrcdir])
    subprocess.check_call(["dpkg-buildpackage", "-uc", "-us", "-Zgzip"], cwd=pkgsrcdir)
    triplet=subprocess.check_output(["dpkg-architecture", "-qDEB_HOST_MULTIARCH"]).decode().strip()
    # then use this to get the static build
    subprocess.check_output("../libtool  --tag=CC   --mode=link gcc   -g -O2 -pthread   -o fc-cache fc-cache.o ../src/.libs/libfontconfig.a /usr/lib/{triplet}/libfreetype.a /usr/lib/{triplet}/libexpat.a /usr/lib/{triplet}/libpng.a -lz -lm".format(triplet=triplet), shell=True, cwd=os.path.join(pkgsrcdir, "fc-cache"))
    target_fc_cache="./fc-cache-{}".format(release)
    shutil.copy(os.path.join(pkgsrcdir, "fc-cache/fc-cache"), target_fc_cache)
    return target_fc_cache
    

if __name__ == "__main__":
    release = sys.argv[1]
    subprocess.check_call(["sudo", "apt-get", "install", "-y", "build-essential"])
    if release != "xenial":
        build_freetype(release)
    build_fontconfig(release)
    
