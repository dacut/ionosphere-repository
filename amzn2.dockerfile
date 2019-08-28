FROM amazonlinux:2
ARG ARCH
ARG PACKAGE
ARG VERSION
ARG REL
ARG REGION=us-west-2
ARG SOURCE_ARCHIVE
ARG TIMEOUT=30

# Reconfigure yum settings.
RUN sed -e "s/timeout=.*/timeout=$TIMEOUT/" /etc/yum.conf > /etc/yum.conf.new
RUN mv /etc/yum.conf.new /etc/yum.conf
RUN echo $REGION > /etc/yum/vars/awsregion

# Update system libraries
RUN yum update -y

# Install rpm-build dependencies
RUN yum install -y rpm-build yum-utils

# The actual build
ENV ARCH=$ARCH
RUN mkdir -p /usr/src/rpm/SOURCES /usr/src/rpm/SPECS
COPY $SOURCE_ARCHIVE /usr/src/rpm/SOURCES/
COPY patches /usr/src/rpm/SOURCES/
COPY SPECS/$PACKAGE.spec /usr/src/rpm/SPECS/$PACKAGE.spec
WORKDIR /usr/src/rpm/SPECS
RUN yum-builddep \
    --define '_topdir /usr/src/rpm' \
    --define "version $VERSION" \
    --define "rel $REL" \
    --assumeyes \
    $PACKAGE.spec
RUN rpmbuild \
    --define '_topdir /usr/src/rpm' \
    --define "version $VERSION" \
    --define "rel $REL" \
    -bb $PACKAGE.spec
RUN rpmbuild \
    --define '_topdir /usr/src/rpm' \
    --define "version $VERSION" \
    --define "rel $REL" \
    -bs $PACKAGE.spec
VOLUME /export

ENTRYPOINT ["/bin/sh", "-c", "mkdir -p /export/SRPMS && mkdir -p /export/RPMS && cp /usr/src/rpm/SRPMS/* /export/SRPMS/ && cp /usr/src/rpm/RPMS/$ARCH/* /export/RPMS/"]
