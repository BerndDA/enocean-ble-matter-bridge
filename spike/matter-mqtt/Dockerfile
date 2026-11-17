# Build:  docker build -t matter-mqtt .
# The container needs host networking (mDNS discovery, IPv6 to Thread devices
# through the border router) and a volume on /data for the fabric state.

FROM rust:1-bookworm AS build
WORKDIR /src

# Dependencies first, so source changes don't rebuild them.
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo 'fn main() {}' > src/main.rs \
    && cargo build --release \
    && rm -rf src

# COPY keeps the files' timestamps, which can be older than the placeholder
# build above; touch them so cargo really compiles the crate.
COPY src ./src
RUN touch src/*.rs && cargo build --release

# Production + CSA test attestation roots, fetched at build time.
COPY fetch-certs.sh ./
RUN ./fetch-certs.sh


FROM gcr.io/distroless/cc-debian12:nonroot
COPY --from=build /src/target/release/matter-mqtt /matter-mqtt
COPY --from=build /src/certs /certs
ENV STORE=/data/controller.bin \
    PAA_DIR=/certs/paa \
    CD_DIR=/certs/cd \
    HTTP=0.0.0.0:8090
VOLUME /data
ENTRYPOINT ["/matter-mqtt"]
