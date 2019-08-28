Name:           aws-checksums
Version:        %{version}
Release:        %{rel}%{dist}
Summary:        AWS HW-accelerated checksum library

License:        ASL 2.0
URL:            https://github.com/awslabs/aws-checksums
Source0:        https://github.com/awslabs/aws-checksums/archive/v%{version}.tar.gz
Patch0:         00-cmake-set-soversion.patch
BuildRequires:  cmake3 binutils gcc make
Provides:       libaws-checksums.so.0unstable
Provides:       libaws-checksums.so.1.0.0

%description
Cross-Platform HW-accelerated CRC32c and CRC32 with fallback to efficient SW
implementations. C interface with language bindings for each of our SDKs.

%prep
%setup -q
%patch0 -p1

%build
cmake3 -DCMAKE_INSTALL_PREFIX:PATH=$RPM_BUILD_ROOT/usr -DBUILD_SHARED_LIBS=on
make %{?_smp_mflags}

%install
rm -rf $RPM_BUILD_ROOT
mkdir -p $RPM_BUILD_ROOT/usr
make %{?_smp_mflags} install

%files
%{_libdir}/libaws-checksums.so.1.0.0
%{_libdir}/libaws-checksums.so.0unstable

%package devel
Summary:        AWS HW-accelerated checksum library (development libaries and headers)
Requires:       aws-checksums
%description devel
Cross-Platform HW-accelerated CRC32c and CRC32 with fallback to efficient SW
implementations. C interface with language bindings for each of our SDKs.

%files devel
%{_libdir}/libaws-checksums.so
%{_libdir}/aws-checksums/cmake/*.cmake
%{_includedir}/aws/checksums/*

%clean
rm -rf $RPM_BUILD_ROOT

%changelog
* Wed Jul 03 2019 Amazon Web Services <https://github.com/awslabs/aws-checksums/issues> - 0.1.3-0
- Fix MSVC ARM Build. It just forwards to the SW implementation, but it's better than nothing.

* Wed Jan 09 2019 Amazon Web Services <https://github.com/awslabs/aws-checksums/issues> - 0.1.2-0
- Windows build fix patch. Install DLLs to the bin directory on windows (#15).
- To avoid taking a new build-time dependency, we copy over the AwsSharedLibSetup.cmake file from aws-c-common.