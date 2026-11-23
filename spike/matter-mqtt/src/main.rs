//! Spike: a Matter controller with its own fabric.
//!
//! Subscribes to every commissioned node and prints one line per report,
//! `<mqtt topic> <json payload>` (the MQTT publish replaces the println once
//! the library is proven against real hardware). Devices are added, labelled
//! and removed through the web UI / REST API in the same process: there must
//! only ever be one process per fabric identity, or they cancel each other's
//! subscriptions.

mod hub;
mod mapping;
mod mqtt;
mod thread;
mod tlv;
mod watcher;
mod web;

use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result};
use clap::Parser;
use matter_controller::{AttestationTrust, FabricConfig, FileStore, MatterController, MatterTime};

#[derive(Parser)]
#[command(about = "Matter fabric -> MQTT spike")]
struct Args {
    /// Controller state: fabric root CA, own credentials, commissioned nodes.
    /// Losing this file means losing the fabric.
    #[arg(long, env = "STORE", default_value = "state/controller.bin")]
    store: PathBuf,

    /// Directory with PAA root certificates (*.der), production and test.
    #[arg(long, env = "PAA_DIR", default_value = "certs/paa")]
    paa_dir: PathBuf,

    /// Directory with CD signing certificates (*.der), production and test.
    #[arg(long, env = "CD_DIR", default_value = "certs/cd")]
    cd_dir: PathBuf,

    /// Topic prefix.
    #[arg(long, env = "PREFIX", default_value = "matter")]
    prefix: String,

    /// Web UI / REST API address. No authentication: anyone who can reach it
    /// can commission and remove devices.
    #[arg(long, env = "HTTP", default_value = "127.0.0.1:8080")]
    http: SocketAddr,

    /// Max interval in seconds a device may stay silent (liveness).
    #[arg(long, default_value_t = 60)]
    max_interval: u16,

    /// Subscribe to everything and keep global attributes (fff8-fffd) too.
    #[arg(long)]
    all: bool,

    /// Also publish every raw value under `<prefix>/raw/<node>/...`.
    #[arg(long)]
    raw: bool,

    /// MQTT broker as host:port, or "none" to disable MQTT.
    #[arg(long, env = "MQTT", default_value = "mqtt.home.seidenspinner.tv:2222")]
    mqtt: String,

    #[arg(long, env = "MQTT_USER")]
    mqtt_user: Option<String>,

    #[arg(long, env = "MQTT_PASSWORD", hide_env_values = true)]
    mqtt_password: Option<String>,

    /// Echo every published message on stdout.
    #[arg(long)]
    print: bool,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "warn".into()),
        )
        .with_writer(std::io::stderr)
        .init();
    let args = Args::parse();
    let controller = open_controller(&args).await?;

    let mqtt = if args.mqtt == "none" {
        None
    } else {
        let (host, port) = args
            .mqtt
            .rsplit_once(':')
            .and_then(|(h, p)| Some((h.trim_matches(['[', ']']).to_owned(), p.parse().ok()?)))
            .with_context(|| format!("--mqtt {}: expected host:port", args.mqtt))?;
        eprintln!("mqtt: broker {host}:{port}");
        Some(mqtt::connect(mqtt::Settings {
            host,
            port,
            user: args.mqtt_user.clone(),
            password: args.mqtt_password.clone(),
            status_topic: format!("{}/status", args.prefix),
        }))
    };
    let hub = hub::Hub::new(
        controller.clone(),
        hub::Config {
            prefix: args.prefix.clone(),
            state_dir: args.store.parent().unwrap_or(Path::new(".")).to_path_buf(),
            max_interval: args.max_interval,
            all: args.all,
            raw: args.raw,
            print: args.print || mqtt.is_none(),
        },
        mqtt.as_ref().map(|(m, _)| m.clone()),
    );
    let mqtt = mqtt.map(|(m, eventloop)| {
        tokio::spawn(mqtt::run(eventloop, m.clone(), hub.clone()));
        m
    });
    for n in controller.nodes().await? {
        hub.start(n.node_id, n.label);
    }

    let listener = tokio::net::TcpListener::bind(args.http)
        .await
        .with_context(|| format!("binding {}", args.http))?;
    eprintln!("web UI on http://{}", args.http);
    axum::serve(listener, web::router(hub.clone()))
        .with_graceful_shutdown(async {
            tokio::signal::ctrl_c().await.ok();
        })
        .await?;
    hub.shutdown();
    if let Some(m) = mqtt {
        m.shutdown().await;
    }
    Ok(())
}

async fn open_controller(args: &Args) -> Result<MatterController> {
    // Production and CSA test roots side by side (fetch-certs.sh puts both
    // into these directories), so certified and development devices work.
    let trust = AttestationTrust::from_dirs(&args.paa_dir, &args.cd_dir).with_context(|| {
        format!(
            "loading attestation roots from {} / {} (run ./fetch-certs.sh)",
            args.paa_dir.display(),
            args.cd_dir.display()
        )
    })?;
    if let Some(dir) = args.store.parent() {
        std::fs::create_dir_all(dir)?;
    }
    let controller = MatterController::builder(Arc::new(FileStore::new(&args.store)))
        .attestation_trust(trust)
        .build()
        .await
        .context("opening controller")?;

    if controller.fabrics().await?.is_empty() {
        // Backdate notBefore so devices with a slightly wrong clock accept it.
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
        controller
            .create_fabric(FabricConfig::new(
                1, // fabric id
                1, // root CA id
                1, // our own node id
                (MatterTime::from_unix_secs(now - 72 * 3600), MatterTime::NO_EXPIRY),
            ))
            .await
            .context("creating fabric")?;
        eprintln!("created new fabric in {}", args.store.display());
    }
    Ok(controller)
}
