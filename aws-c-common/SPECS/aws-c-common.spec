Name:           aws-c-common
Version:        %{version}
Release:        %{rel}%{dist}
Summary:        AWS C Common

License:        ASL 2.0
URL:            https://github.com/awslabs/aws-c-common
Source0:        https://github.com/awslabs/aws-c-common/archive/v%{version}.tar.gz
BuildRequires:  cmake3 binutils gcc make
Provides:       libaws-c-common.so.0unstable
Provides:       libaws-c-common.so.1.0.0

%description
The AWS SDK for C++ provides a modern C++ (version C++ 11 or later)
interface for Amazon Web Services (AWS). It is meant to be performant and
fully functioning with low- and high-level SDKs, while minimizing
dependencies and providing platform portability (Windows, OSX, Linux, and
mobile).

%prep
%setup -q

%build
cmake3 -DCMAKE_INSTALL_PREFIX:PATH=$RPM_BUILD_ROOT/usr -DBUILD_SHARED_LIBS=on
make %{?_smp_mflags}

%install
rm -rf $RPM_BUILD_ROOT
mkdir -p $RPM_BUILD_ROOT/usr
make %{?_smp_mflags} install

%files
%{_libdir}/libaws-c-common.so.1.0.0
%{_libdir}/libaws-c-common.so.0unstable

%package devel
Summary:        AWS C Common (development libaries and headers)
Requires:       aws-c-common
%description devel
The AWS SDK for C++ provides a modern C++ (version C++ 11 or later)
interface for Amazon Web Services (AWS). It is meant to be performant and
fully functioning with low- and high-level SDKs, while minimizing
dependencies and providing platform portability (Windows, OSX, Linux, and
mobile).

%files devel
%{_libdir}/libaws-c-common.so
%{_libdir}/cmake/*.cmake
%{_libdir}/aws-c-common/cmake/*.cmake
%{_includedir}/aws/common/*
%{_includedir}/aws/testing/*

%clean
rm -rf $RPM_BUILD_ROOT

%changelog
* Thu Aug 01 2019 Amazon Web Services <https://github.com/awslabs/aws-c-common/issues> - 0.4.3-0
- Depend on pthreads via Threads rather than manually (#473)
