# matter-mqtt spike

A Matter controller with its **own fabric**. Devices join it as an additional admin (they stay in
Apple/Google Home); it subscribes to every commissioned node and publishes the values as readable,
retained MQTT topics like `matter/ble-gateway/bad/temperature 19.4`. Built on
[`matter-controller`](https://github.com/phunapps/matter-rust).

Still a spike, running on the Pi (see Docker) to prove itself unattended.

## Setup

```sh
./fetch-certs.sh                 # production + CSA test attestation roots -> certs/
cargo build --release
```

`state/controller.bin` is created on first start and **is the fabric** (root CA key, node list).
Lose it and every device has to be commissioned again.

## Running

```sh
./target/release/matter-mqtt                       # web UI on http://127.0.0.1:8080
./target/release/matter-mqtt --http 0.0.0.0:8080   # reachable from the LAN
./target/release/matter-mqtt --mqtt none --print   # no MQTT, messages on stdout
RUST_LOG=debug ./target/release/matter-mqtt        # protocol logging to stderr
```

One process does everything: it subscribes to all commissioned nodes, publishes to MQTT and serves
the web UI / REST API for adding, labelling and removing devices. Never run two instances on the
same `state/`: they share one fabric identity and cancel each other's subscriptions.

The web server has **no authentication**. Anyone who can reach it can commission and remove
devices, hence the localhost default.

## MQTT

| Option | Env | Default |
|---|---|---|
| `--mqtt host:port` (`none` disables) | `MQTT` | `mqtt.home.seidenspinner.tv:2222` |
| `--mqtt-user` | `MQTT_USER` | none |
| `--mqtt-password` | `MQTT_PASSWORD` | none |
| `--prefix` | | `matter` |
| `--print` (echo every message on stdout) | | off, on with `--mqtt none` |

Plain TCP, MQTT 3.1.1, client id `matter-mqtt`, QoS 1.

- Values, `info` and `online` topics are **retained**; events are not.
- `<prefix>/status` is `online` while the bridge is connected; `offline` is its last will and is
  also sent on a clean shutdown, together with `online false` for every device.
- After every (re)connect the complete state is published again, so a broker restarted without
  persistence is refilled.
- A renamed device or endpoint gets its old retained topics deleted (empty retained payload); a
  removed device gets all of them deleted.
- Messages are queued (10,000) while the broker is unreachable; beyond that they are dropped, the
  republish after reconnecting restores the state.

## Docker

```sh
docker build -t matter-mqtt .
docker run -d --name matter-mqtt --network host -v ./state:/data \
    -e MQTT=127.0.0.1:2222 matter-mqtt
```

- `rust:1-bookworm` builds, `gcr.io/distroless/cc-debian12:nonroot` runs (55 MB, no shell). The
  attestation roots are fetched at build time into `/certs`.
- **Host networking is required**: devices are found via mDNS and reached over IPv6 (Thread devices
  through the border router), neither works through Docker's bridge NAT.
- `/data` holds the fabric (`controller.bin`, `events-<node>.txt`). Moving an existing setup means
  copying `state/` into it, and never running the old instance again.
- Defaults inside the image: `STORE=/data/controller.bin`, `HTTP=0.0.0.0:8090`; set `MQTT` (and
  optionally `MQTT_USER`, `MQTT_PASSWORD`, `PREFIX`) via the environment.

On the Pi it runs from the home-automation compose file, built straight from this repo:

```yaml
  matter-mqtt:
    image: matter-mqtt:latest
    build:
      context: https://github.com/BerndDA/enocean-ble-matter-bridge.git#main:spike/matter-mqtt
    restart: unless-stopped
    network_mode: host
    user: "1000:1000"
    environment:
      - MQTT=127.0.0.1:2222
      - HTTP=0.0.0.0:8090
    volumes:
      - ./volumes/matter-mqtt:/data
```

Update: `docker compose build matter-mqtt && docker compose up -d matter-mqtt`.

## Adding a device (multi-admin)

The device stays in Apple/Google Home; we join it as an additional admin:

1. In Apple Home: device → settings → *Turn On Pairing Mode* (Google Home: *Linked Matter apps &
   services* → *Link apps & services*). Note the 11-digit setup code.
2. Within the shown window (usually 15 min), enter it under *Add device* in the web UI.

Thread devices are reached through the existing border router; this host only needs IPv6 on the
same LAN. Development devices with test DACs (vendor `0xFFF1`, e.g. DIY ESP32 builds or our own
nRF52840 builds) work too: `fetch-certs.sh` adds the CSA test roots next to the production ones.

## REST API

```sh
curl localhost:8080/api/nodes                                   # list, online state
curl localhost:8080/api/nodes/2                                 # current values + recent events
curl -X POST localhost:8080/api/nodes -H 'content-type: application/json' \
     -d '{"code": "12345678901", "label": "kitchen-plug"}'      # commission
curl -X PUT localhost:8080/api/nodes/2/fabric-label -H 'content-type: application/json' \
     -d '{"label": "MQTT bridge"}'                              # our fabric's label on the device
curl -X DELETE localhost:8080/api/nodes/2                       # RemoveFabric + forget
curl -X DELETE 'localhost:8080/api/nodes/2?local_only=true'     # forget only (device gone)
curl 'localhost:8080/api/nodes/4/read?ep=0&cluster=0x28'        # debug read, omitted = wildcard
curl localhost:8080/api/thread                                  # Thread neighbor/route tables of all nodes
```

The web UI's *Thread network* card draws the mesh from `/api/thread` (read on load, every 60 s and
on *Refresh*): Thread Network Diagnostics (`0035`) neighbor and route tables, matched up by the
extended address each node reports in General Diagnostics `NetworkInterfaces`. Links are colored by
LQI and labelled with the average RSSI at the end that measured it. Dashed means one-sided: only one
of our nodes lists the other, or the route table says the link isn't established. Routers that
aren't on this fabric (e.g. the border router) appear only through our nodes' tables.

The fabric label is what the device stores for our fabric. The vendor shown next to it
("Test vendor") comes from the admin vendor id `0xFFF1`, fixed at commissioning.

## Output

Published messages (shown here as `--print` writes them; status messages go to stderr):

```text
matter/nuki/online                          true
matter/nuki/info                            {"product":"Nuki Matter Bridge","vendor":"DIY",...}
matter/nuki/front-door/info                 {"device_types":["door_lock"],"endpoints":[2],"name":"Front door",...}
matter/nuki/front-door/lock_state           locked
matter/nuki/front-door/battery              66
matter/ble-gateway/bad/temperature          19.4
matter/ble-gateway/bad/setpoint             18.0
matter/ble-gateway/sensor-54aa/humidity     50.8
matter/enocean-gateway/kuechenradio/power   0.0
matter/nuki/front-door/event/lock_operation {"operation":"unlock","source":"manual","user":null}
```

Topic: `<prefix>/<device>/<endpoint>/<property>`.

- **device**: the label given at commissioning (else the device's NodeLabel / ProductName).
- **endpoint**: the bridged device's name ("Küche links 1" → `kueche-links-1`), else `ep<N>`.
  Endpoints of one physical device (same UniqueID, e.g. a BLE sensor split into a temperature and a
  humidity endpoint) share one name. Different devices with the same name get `-<N>` appended.
- **property**: from the table in [src/mapping.rs](src/mapping.rs), values converted (°C, %, W,
  enum names). Strings are sent without quotes, everything else as JSON.
- `.../info` per device and per endpoint: static metadata as one JSON payload.

Only mapped attributes are published, and only when they change. Mapped topics start after the
first complete read of a node, so a value never shows up under a temporary name. Unmapped values
are visible in the web UI (*Raw values*); `--raw` also publishes them as
`<prefix>/raw/<node>/<endpoint>/<cluster>/<attribute>`. To support a new device type, add its
attributes to `mapping::attribute` (and events to `mapping::event`).

What gets subscribed (one subscription per node):

- endpoint 0: only BasicInformation (`0028`) and the endpoint list (`001d/0003`); the rest of
  endpoint 0 is certificates, ACLs and diagnostics. A changed endpoint list (bridge got a new
  device) rebuilds the subscription.
- every other endpoint: all clusters, attributes and events.
- global attributes (`fff8`-`fffd`) are not printed.
- `--all` subscribes to everything with one wildcard path and prints everything. That is also
  the fallback when a device rejects the multi-path subscription.

Known limits of `matter-controller` 0.18.3 and how the spike works around them:

- The priming report cannot be trusted to be complete. Its buffer is fixed at 256 reports (a drop is
  signalled as `reports dropped`), and a notification spanning more than 64 chunks loses its head
  **silently**. Thread devices send small chunks, so the EnOcean gateway's priming report lost
  endpoints 0 to 4. The spike therefore reads every subscribed path separately after each
  (re)established subscription. Later changes are unaffected: they arrive as small reports.
- The first subscribe always replays the device's event buffer. The spike stores the last event
  number per node in `state/events-<node>.txt` and skips everything up to it. On first contact it
  reads the event history once to set that starting point.

## What to check

- commissioning via the pairing code works for each device type we have
- the priming report covers all endpoints (wildcard subscribe)
- the subscription survives a device reboot or power loss (`online false` → `true`)
- Thread sleepy devices (ICDs) keep reporting
- memory: `ps -o rss= -p $(pgrep matter-mqtt)` (5.9 MB with one node, the Nuki Matter Bridge)
