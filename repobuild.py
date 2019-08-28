#!/usr/bin/env python3
"""
Ionosphere repository build orchestration.
"""
from enum import Enum
from logging import basicConfig as log_config, getLogger, DEBUG
from os import link, lstat, mkdir, walk
from os.path import abspath, exists, join as path_join, split as path_split
from platform import machine, system as system_name
from re import compile as re_compile
from shutil import copy2, rmtree
from sys import argv
from tempfile import mkdtemp
from threading import Condition, local
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence
from urllib.parse import unquote_plus as url_unquote_plus, urlparse
from urllib.request import urlopen

import docker
from docker.errors import BuildError, ContainerError
from docker.models.images import Image
import yaml

# pylint: disable=invalid-name,too-many-instance-attributes,too-many-arguments

READ_BUFFER_SIZE = 1 << 20
LOG_STRIP_PATTERN = re_compile(r"^(?:[ \n]*\n)?((?:.|\n+.)*)(?:\n[ \n]*)?$")

log = getLogger("ionosphere.repobuild")


class Package:
    """
    Data model for a software package.
    """
    def __init__(self, name: str, version: str, download_url: str,
                 dependencies: Dict[str, str]) -> None:
        """
        Create a new Package.
        """
        super(Package, self).__init__()
        self.name = name
        self.version = version
        self.download_url = download_url
        self.dependencies = dict(dependencies)

    @property
    def source_archive_name(self) -> str:
        """
        The base filename of the source archive.
        """
        return path_split(
            url_unquote_plus(urlparse(self.resolved_download_url).path))[-1]

    @property
    def resolved_download_url(self) -> str:
        """
        The download_url resolved with variables replaced.
        """
        arch = machine()
        return self.download_url.format(
            Arch=arch, Architecture=arch, Name=self.name,
            System=system_name(), Version=self.version)

    @classmethod
    def from_yaml_config(cls, config: Dict[str, Any]) -> "Package":
        name = config["Name"]
        version = config["Version"]
        download_url = config["URL"]
        dependencies: Dict[str, str] = config.get("Dependencies", {})

        return cls(name=name, version=version, download_url=download_url,
                   dependencies=dependencies)


class PackageType(Enum):
    """
    Type of package being produced (RPM or DEB).
    """
    RPM = "rpm"
    DEB = "deb"


class PlatformInfo(NamedTuple):
    """
    Variables for a given platform to build for.
    """
    name: str
    arch: str
    source_docker_image: str
    package_type: PackageType


class Platform(Enum):
    """
    Platforms we know how to build against.
    """
    amzn1_x86_64 = PlatformInfo(
        "amzn1", "x86_64", "amazonlinux:1", PackageType.RPM)
    amzn2_x86_64 = PlatformInfo(
        "amzn2", "x86_64", "amazonlinux:2", PackageType.RPM)
    el7_x86_64 = PlatformInfo(
        "el7", "x86_64", "centos:7", PackageType.RPM)
    ubuntu_1604_x86_64 = PlatformInfo(
        "ubuntu-xenial", "amd64", "ubuntu:16.04", PackageType.DEB)
    ubuntu_1804_x86_64 = PlatformInfo(
        "ubuntu-bionic", "amd64", "ubuntu:18.04", PackageType.DEB)
    ubuntu_1810_x86_64 = PlatformInfo(
        "ubuntu-cosmic", "amd64", "ubuntu:18.10", PackageType.DEB)
    ubuntu_1904_x86_64 = PlatformInfo(
        "ubuntu-disco", "amd64", "ubuntu:19.04", PackageType.DEB)

    @property
    def os_name(self) -> str:
        """
        The short OS name (amzn1, amzn2, el7, etc.); used in RPM suffixes.
        """
        return self.value.name              # pylint: disable=no-member

    @property
    def arch(self) -> str:
        """
        The processor architecture; used in package names (OS-specific;
        notably RPM-based OSes use x86_64, while DEB-based OSes use amd64).
        """
        return self.value.arch              # pylint: disable=no-member

    @property
    def source_docker_image(self) -> str:
        """
        The Docker image used for building.
        """
        return self.value.source_docker_image  # pylint: disable=no-member

    @property
    def package_type(self) -> PackageType:
        """
        The type of packages (RPM, DEB) used by the OS.
        """
        return self.value.package_type      # pylint: disable=no-member

    @property
    def dockerfile_template(self) -> str:
        """
        The name of the docker template used to build the Docker image.
        """
        return f"{self.os_name}.dockerfile"


class SourcePackageState(Enum):
    """
    State of a source package download.
    """
    InProgress = 1
    Downloaded = 2
    Failed = 3


class PackageBuild:
    """
    Build orchestration for a single package.
    """
    thread_local = local()
    source_state: Dict[str, SourcePackageState] = {}
    download_cond = Condition()

    def __init__(
            self, package: Package, platform: Platform, build_root: str,
            package_root: str, remove_build_dir: bool = True) -> None:
        """
        Create a new PackageBuild instance. This also creates the temporary
        build directory used for creating the Docker image.
        """
        super(PackageBuild, self).__init__()
        self.package = package
        self.platform = platform
        self.build_root = build_root
        self.package_root = package_root
        self.package_dir = path_join(package_root, package.name)
        self.build_dir = abspath(mkdtemp(
            prefix=(f'{package.name.replace("/", "-")}-'
                    f'{package.version.replace("/", "-")}-{platform.name}-'
                    f'{platform.arch}'),
            dir=build_root))
        self.remove_build_dir = remove_build_dir
        self.staged = False
        self.image: Optional[Image] = None

    def __del__(self):
        """
        Perform cleanup operations on the PackageBuild instance. If
        remove_build_dir is set, this will remove the build directory created
        during initialization.
        """
        if self.remove_build_dir:
            rmtree(self.build_dir)

    @property
    def docker(self):
        """
        A thread-local Docker client.
        """
        try:
            result = PackageBuild.thread_local.docker
        except AttributeError:
            result = PackageBuild.thread_local.docker = \
                docker.from_env(timeout=300)

        return result

    @property
    def source_archive_path(self) -> str:
        """
        The full path to the downloaded source archive.
        """
        return path_join(self.package_dir, self.package.source_archive_name)

    def download_source_package(self) -> bool:
        """
        Download the package if it does not already exist. The return value
        indicates if a download was made.
        """
        while True:
            with self.download_cond:
                state = self.source_state.get(self.package.name)
                if state is None or state == SourcePackageState.Failed:
                    # No download in progress; do it.
                    self.source_state[self.package.name] = \
                        SourcePackageState.InProgress
                    break

                if state == SourcePackageState.Downloaded:
                    # Already downloaded.
                    return False

                # Wait until we get a notification about the download, then
                # try again.
                assert state == SourcePackageState.InProgress
                self.download_cond.wait()

        # If we broke out of the wait loop, we own downloading the package.
        try:
            if not exists(self.package_dir):
                mkdir(self.package_dir)

            with urlopen(self.package.resolved_download_url) as req:
                with open(self.source_archive_path, "wb") as fd:
                    buffer = bytearray(READ_BUFFER_SIZE)
                    content_length = int(req.getheader("Content-Length"))
                    total_read = 0

                    while total_read < content_length:
                        n_read = req.readinto(buffer)
                        if n_read == 0:
                            raise ValueError(
                                f"Failed to read entire contents of "
                                f"{self.package.resolved_download_url}: "
                                f"read {total_read} byte(s); expected "
                                f"{content_length} byte(s)",
                                self.package.resolved_download_url,
                                total_read, content_length)

                        if n_read < READ_BUFFER_SIZE:
                            fd.write(buffer[:n_read])
                        else:
                            fd.write(buffer)

                        total_read += n_read
            with self.download_cond:
                self.source_state[self.package.name] = \
                    SourcePackageState.Downloaded
            return True
        except:                                     # noqa
            with self.download_cond:
                self.source_state[self.package.name] = \
                    SourcePackageState.Failed
            raise

    @property
    def staged_archive(self) -> str:
        """
        The path to the staged source archive.
        """
        return path_join(self.build_dir, self.package.source_archive_name)

    @property
    def staged_dockerfile(self) -> str:
        """
        The path to the staged Dockerfile.
        """
        return path_join(self.build_dir, "Dockerfile")

    @property
    def buildargs(self) -> Dict[str, str]:
        """
        The build arguments to pass to Docker while building the image.
        """
        return {
            "ARCH": self.platform.arch,
            "OS_NAME": self.platform.os_name,
            "PACKAGE": self.package.name,
            "REGION": "us-west-2",
            "REL": "0",
            "SOURCE_ARCHIVE": self.package.source_archive_name,
            "VERSION": self.package.version,
        }

    def stage_files(self) -> None:
        """
        Copy files from the source directory to the staging directory.
        """
        self.download_source_package()

        # Are the package directory and build directory on the same filesystem?
        # If so, just create hard-links to save on disk space and run faster.
        package_dev = lstat(self.package.name).st_dev
        build_dev = lstat(self.build_dir).st_dev
        if package_dev == build_dev:
            log.debug("Package directory and build directory reside on the "
                      "same filesystem; using link to copy files")
            copy_function: Callable[[str, str], Any] = link
        else:
            log.debug("Package directory and build directory reside on "
                      "different filesystems (%d vs %d); using copy2 to "
                      "copy files", package_dev, build_dev)
            copy_function = copy2

        # Copy the bits in the package directory so they're available to the
        # Docker builder.
        log.debug("Copying (recursively) %s to %s", self.package.name,
                  self.build_dir)

        # We can't use copytree here -- it insists on build_dir not existing,
        # which is problematic for us.
        package_source = abspath(self.package.name)
        for source_dir, subdirs, filenames in walk(package_source):
            target_dir = path_join(
                self.build_dir, source_dir[len(package_source):].lstrip("/"))

            for filename in filenames:
                source_path = path_join(source_dir, filename)
                target_path = path_join(target_dir, filename)
                log.debug("Copying %s to %s", source_path, target_path)
                copy_function(source_path, target_path)

            for subdir in subdirs:
                target_path = path_join(target_dir, subdir)
                log.debug("Creating %s", target_path)
                mkdir(target_path)

        # Copy the package itself.
        log.debug("Copying %s to %s", self.source_archive_path,
                  self.staged_archive)
        copy_function(
            abspath(self.source_archive_path), self.staged_archive)

        # Copy the Dockerfile.
        log.debug("Copying %s to %s", self.platform.dockerfile_template,
                  self.staged_dockerfile)
        copy_function(
            abspath(self.platform.dockerfile_template), self.staged_dockerfile)

        self.staged = True

    def build(self) -> None:
        """
        Perform the build.
        """
        if not self.staged:
            raise ValueError("Files have not been staged for building")

        try:
            self.image, build_logs = self.docker.images.build(
                dockerfile=self.staged_dockerfile, path=self.build_dir,
                rm=True, buildargs=self.buildargs)
        except BuildError as e:
            log.error("Failed to build %s-%s (%s %s): %s", self.package.name,
                      self.package.version, self.platform.os_name,
                      self.platform.arch, e)
            for log_entry in e.build_log:
                if "stream" in log_entry:
                    m = LOG_STRIP_PATTERN.match(log_entry["stream"])
                    assert m, "m failed to match %r" % log_entry["stream"]
                    log.info("    %s", m.group(1))

                if "errorDetail" in log_entry:
                    m = LOG_STRIP_PATTERN.match(log_entry["errorDetail"]["message"])
                    assert m
                    log.error("   %s", m.group(1))
            raise

        log.debug("Build logs: %s", build_logs)

    def export(self, dest_root: str) -> None:
        """
        Export files from the build.
        """
        if self.image is None:
            raise ValueError("Image has not been built")

        try:
            logs = self.docker.containers.run(
                self.image.id,
                volumes={dest_root: {"bind": "/export", "mode": "rw"}},
                detach=False, stdout=True, stderr=True, remove=True)
        except ContainerError as e:
            log.error("Failed to export %s-%s (%s %s): %s", self.package.name,
                      self.package.version, self.platform.os_name,
                      self.platform.arch, e)

            stdout = getattr(e, "stdout", None)
            if stdout:
                m = LOG_STRIP_PATTERN.match(stdout.decode("utf-8"))
                assert m
                log.info("    %s", m.group(1))

            stderr = getattr(e, "stderr", None)
            if stderr:
                m = LOG_STRIP_PATTERN.match(stderr.decode("utf-8"))
                assert m
                log.error("    %s", m.group(1))
            raise
        log.debug("Build logs: %s", logs)


def main(args: Sequence[str]) -> int:
    """
    The main entrypoint.
    """
    log_config(level=DEBUG)

    packages: List[Package] = []
    package_root = abspath("./packages")
    build_root = abspath("./builds")
    dist_root = abspath("./dist")

    if not exists(build_root):
        mkdir(build_root)

    if not exists(package_root):
        mkdir(package_root)

    if not exists(dist_root):
        mkdir(dist_root)

    log.debug("build_root: %s", build_root)
    log.debug("package_root: %s", package_root)

    with open("packages.yaml", "r") as fd:
        package_infos = yaml.safe_load(fd)
        for package_info in package_infos:
            packages.append(Package.from_yaml_config(package_info))

    for platform in Platform:
        for package in packages:
            pb = PackageBuild(
                package=package, platform=platform, build_root=build_root,
                package_root=package_root, remove_build_dir=False)

            pb.stage_files()
            pb.build()
            pb.export(dest_root=path_join(dist_root, platform.os_name))

    return 0


if __name__ == "__main__":
    exit(main(argv[1:]))
