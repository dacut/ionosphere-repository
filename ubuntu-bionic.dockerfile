FROM ubuntu:bionic
ARG ARCH
ARG PACKAGE
ARG VERSION
ARG REL
ARG SOURCE_ARCHIVE

# Update system libraries
ENV DEBIAN_FRONTEND=noninteractive
RUN apt update -y

# Install Debian build dependencies
RUN apt install -y binutils build-essential debhelper devscripts equivs dh-make

# The actual build
RUN mkdir /build
COPY $SOURCE_ARCHIVE /build/${PACKAGE}_${VERSION}.orig.tar.gz
WORKDIR /build
RUN tar xf ${PACKAGE}_${VERSION}.orig.tar.gz
RUN mv ${PACKAGE}-${VERSION} ${PACKAGE}_${VERSION}-${REL}
COPY debian /build/${PACKAGE}_${VERSION}-${REL}/debian/
COPY patches/* /build/${PACKAGE}_${VERSION}-${REL}/debian/patches/
RUN sed -e "s/@VERSION@/${VERSION}/g" \
    /build/${PACKAGE}_${VERSION}-${REL}/debian/substvars.in \
    > /build/${PACKAGE}_${VERSION}-${REL}/debian/substvars
WORKDIR /build/${PACKAGE}_${VERSION}-${REL}
RUN mk-build-deps debian/control
RUN dpkg --install ${PACKAGE}-build-deps_${VERSION}_all.deb || apt-get install --fix-broken --yes && rm ${PACKAGE}-build-deps_${VERSION}_all.deb
RUN dpkg-checkbuilddeps
RUN dpkg-buildpackage
VOLUME /export

CMD ["/bin/bash", "-c", "shopt -s nullglob; cp -f /build/*.deb /build/*.dsc /build/*.changes /build/*.debian.tar.* /build/*.orig.tar.* /export/"]