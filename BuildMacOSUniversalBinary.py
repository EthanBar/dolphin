#!/usr/bin/env python3
"""
The current tooling supported in CMake, Homebrew, and QT5 are insufficient for
creating MacOSX universal binaries automatically for applications like Dolphin
which have more complicated build requirements (like different libraries, build
flags and source files for each target architecture).

So instead, this script manages the configuration and compilation of distinct
builds and project files for each target architecture and then merges the two
binaries into a single universal binary.

Running this script will:
1) Generate Xcode project files for the ARM build (if project files don't
   already exist)
2) Generate Xcode project files for the x64 build (if project files don't
   already exist)
3) Build the ARM project for the selected build_target
4) Build the x64 project for the selected build_target
5) Generates universal .app packages combining the ARM and x64 packages
6) Utilizes the lipo tool to combine the binary objects inside each of the
   packages into universal binaries
7) Code signs the final universal binaries using the specified
   codesign_identity
"""

import glob
import sys
import os
import shutil
import filecmp
import argparse
import subprocess

# #BEGIN CONFIG# #

# The config variables listed below are the defaults, but they can be
# overridden by command line arguments see parse_args(), or run:
# BuildMacOSUniversalBinary.py --help


# Location of destination universal binary
dst_app = "universal/"
# Build Target (dolphin-emu to just build the emulator and skip the tests)
build_target = "ALL_BUILD"

# Locations to pkg config files for arm and x64 libraries
# The default values of these paths are taken from the default
# paths used for homebrew
pkg_config_path = {
    "arm64":  '/opt/homebrew/lib/pkgconfig',
    "x86_64": '/usr/local/lib/pkgconfig'
}

# Locations to qt5 directories for arm and x64 libraries
# The default values of these paths are taken from the default
# paths used for homebrew
qt5_path = {
    "arm64":  '/opt/homebrew/opt/qt5',
    "x86_64": '/usr/local/opt/qt5'
}

# Identity to use for code signing. "-" indicates that the app will not
# be cryptographically signed/notarized but will instead just use a
# SHA checksum to verify the integrity of the app. This doesn't
# protect against malicious actors, but it does protect against
# running corrupted binaries and allows for access to the extended
# permisions needed for ARM builds

codesign_identity = '-'

# # END CONFIG # #

# Architectures to build for. This is explicity left out of the command line
# config options for several reasons:
# 1) Adding new architectures will generally require more code changes
# 2) Single architecture builds should utilize the normal generated cmake
#    project files rather than this wrapper script

architectures = ["x86_64", "arm64"]

# Minimum macOS version for each architecture slice
mac_os_deployment_target={
    "arm64": "10.14.0",
    "x86_64": "10.12.0"
}

def parse_args():
    global dst_app, build_target, pkg_config_path, qt5_path, codesign_identity

    parser = argparse.ArgumentParser(formatter_class=
                                     argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument('--target',
        help='Build target in generated project files',
        default=build_target)

    parser.add_argument('--dst_app',
        help='Directory where universal binary will be stored',
        default=dst_app)

    parser.add_argument('--codesign',
        help='Code signing identity to use to sign the applications',
        default=codesign_identity)

    for arch in architectures:
        parser.add_argument('--{}_pkg_config'.format(arch),
             help="Folder containing .pc files for {} libraries".format(arch),
             default=pkg_config_path[arch])

        parser.add_argument('--{}_qt5_path'.format(arch),
             help="Install path for {} qt5 libraries".format(arch),
             default=qt5_path[arch])

    args = vars(parser.parse_args());
    dst_app = args["dst_app"]
    build_target = args["target"]
    codesign_identity = args["codesign"]

    for arch in architectures:
        pkg_config_path[arch] = args["{}_pkg_config".format(arch)]
        qt5_path[arch] = args["{}_qt5_path".format(arch)]


def lipo(path0,path1,dst):
    if subprocess.call(['lipo', '-create', '-output', dst, path0, path1]) != 0:
        print("WARNING: {} and {} are different but can not be lipo'd, keeping {}".format(path0, path1, path0));
        shutil.copy(path0, dst)

# Merges two build trees together for different architectures into a single
# universal binary.
# The rules for merging are:
# 1) Files that exist in either src tree are copied into the dst tree
# 2) Files that exist in both trees and are identical are copied over
#    unmodified
# 3) Files that exist in both trees and are non-identical are lipo'd
# 4) Symlinks are created in the destination tree to mirror the hierarchy in
#    the source trees

def recursiveMergeBinaries(src0,src1,dst):
    #loop over all files in src0
    for newpath0 in glob.glob(src0+"/*"):
        filename = os.path.basename(newpath0);
        newpath1 = os.path.join(src1,filename);
        new_dst_path = os.path.join(dst,filename);
        if not os.path.islink(newpath0):
            if os.path.exists(newpath1):
                if os.path.isdir(newpath1):
                    os.mkdir(new_dst_path);
                    #recurse into directories
                    recursiveMergeBinaries(newpath0,newpath1,new_dst_path)
                else:
                    if filecmp.cmp(newpath0,newpath1):
                        #copy files that are the same
                        shutil.copy(newpath0,new_dst_path);
                    else:
                        #lipo together files that are different
                        lipo(newpath0,newpath1,new_dst_path)
            else:
              #copy files that don't exist in path1
              shutil.copy(newpath0,new_dst_path)

    #loop over files in src1 and copy missing things over to dst
    for newpath1 in glob.glob(src1+"/*"):
        filename = os.path.basename(newpath0);
        newpath0 = os.path.join(src0,filename);
        new_dst_path = os.path.join(dst,filename);
        if not os.path.exists(newpath0) and not os.path.islink(newpath1):
            shutil.copytree(newpath1,new_dst_path);

    #fix up symlinks for path0
    for newpath0 in glob.glob(src0+"/*"):
        filename = os.path.basename(newpath0);
        new_dst_path = os.path.join(dst,filename);
        if os.path.islink(newpath0):
            relative_path = os.path.relpath(os.path.realpath(newpath0),src0)
            os.symlink(relative_path,new_dst_path);
    #fix up symlinks for path1
    for newpath1 in glob.glob(src1+"/*"):
        filename = os.path.basename(newpath1);
        new_dst_path = os.path.join(dst,filename);
        newpath0 = os.path.join(src0,filename);
        if os.path.islink(newpath1) and not os.path.exists(newpath0):
            relative_path = os.path.relpath(os.path.realpath(newpath1),src1)
            os.symlink(relative_path,new_dst_path);

    return;

def build():
    # Configure and build single architecture builds for each architecture
    for arch in architectures:
        # Create build directory for architecture
        if not os.path.exists(arch):
            os.mkdir(arch);
        # Setup environment variables for build
        envs = os.environ.copy();
        envs['PKG_CONFIG_PATH'] = pkg_config_path[arch];
        envs['Qt5_DIR'] = qt5_path[arch];
        envs['CMAKE_OSX_ARCHITECTURES']=arch;

        subprocess.check_call([
                'arch', '-'+arch,
                'cmake', '../../', '-G', 'Xcode',
                '-DCMAKE_OSX_DEPLOYMENT_TARGET='+mac_os_deployment_target[arch]
            ],
            env=envs,cwd=arch);

        # Build project
        subprocess.check_call(['xcodebuild',
                               '-project', 'dolphin-emu.xcodeproj',
                               '-target', build_target,
                               '-configuration', 'Release'],cwd=arch);

    # Merge ARM and x64 binaries into universal binaries

    # Source binary trees to merge together
    src_app0 = architectures[0]+"/Binaries/release"
    src_app1 = architectures[1]+"/Binaries/release"


    if os.path.exists(dst_app):
        shutil.rmtree(dst_app)

    os.mkdir(dst_app);
    # create univeral binary
    recursiveMergeBinaries(src_app0,src_app1,dst_app);
    # codesign
    for path in glob.glob(dst_app+"/*"):
        subprocess.check_call(
            ['codesign', '--deep', '--force', '-s', codesign_identity, path]);

if __name__ == "__main__":
    parse_args();
    build();
    print("Built Universal Binary successfully!")
