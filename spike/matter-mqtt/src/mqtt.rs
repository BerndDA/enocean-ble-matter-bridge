//! MQTT connection. Publishing never blocks the caller: messages go into the
//! client's queue and the event loop task sends them. After every (re)connect
//! the hub republishes its whole retained state, so a broker that lost its
//! retained messages (restart without persistence) is refilled.

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use rumqttc::{AsyncClient, Event, EventLoop, LastWill, MqttOptions, Packet, QoS};

use crate::hub::Hub;

/// Queue between the hub and the event loop. A full queue (broker unreachable
/// for long) drops messages; the republish after reconnecting covers state.
const QUEUE: usize = 10_000;

pub struct Settings {
    pub host: String,
    pub port: u16,
    pub user: Option<String>,
    pub password: Option<String>,
    /// `<prefix>/status`: "online", "offline" as last will.
    pub status_topic: String,
}

#[derive(Clone)]
pub struct Mqtt {
    client: AsyncClient,
    status_topic: String,
    stopping: Arc<AtomicBool>,
}

pub fn connect(s: Settings) -> (Mqtt, EventLoop) {
    // A fixed client id: a second instance kicks the first off the broker,
    // which is wanted, there must only be one per fabric.
    let mut opts = MqttOptions::new("matter-mqtt", s.host, s.port);
    opts.set_keep_alive(Duration::from_secs(30))
        .set_max_packet_size(256 * 1024, 256 * 1024)
        .set_last_will(LastWill::new(&s.status_topic, "offline", QoS::AtLeastOnce, true));
    if let Some(user) = s.user {
        opts.set_credentials(user, s.password.unwrap_or_default());
    }
    let (client, eventloop) = AsyncClient::new(opts, QUEUE);
    (Mqtt { client, status_topic: s.status_topic, stopping: Arc::default() }, eventloop)
}

impl Mqtt {
    /// An empty retained payload deletes the retained message on the broker.
    pub fn publish(&self, topic: &str, payload: String, retain: bool) {
        if let Err(e) = self.client.try_publish(topic, QoS::AtLeastOnce, retain, payload) {
            eprintln!("mqtt: dropping {topic}: {e}");
        }
    }

    fn online(&self) {
        self.publish(&self.status_topic, "online".into(), true);
    }

    /// Clean shutdown: "offline" (the broker only sends the last will on an
    /// unclean disconnect), then disconnect once the queue is flushed.
    pub async fn shutdown(&self) {
        self.publish(&self.status_topic, "offline".into(), true);
        tokio::time::sleep(Duration::from_millis(500)).await;
        self.stopping.store(true, Ordering::Relaxed);
        self.client.disconnect().await.ok();
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
}

/// Drives the connection; rumqttc reconnects on the next poll after an error.
pub async fn run(mut eventloop: EventLoop, mqtt: Mqtt, hub: Arc<Hub>) {
    let mut connected = false;
    loop {
        match eventloop.poll().await {
            Ok(Event::Incoming(Packet::ConnAck(ack))) => {
                eprintln!("mqtt: connected ({:?})", ack.code);
                connected = true;
                mqtt.online();
                hub.republish();
            }
            Ok(_) => {}
            Err(_) if mqtt.stopping.load(Ordering::Relaxed) => return,
            Err(e) => {
                if connected {
                    eprintln!("mqtt: connection lost: {e}");
                } else {
                    eprintln!("mqtt: cannot connect: {e}, retrying");
                }
                connected = false;
                tokio::time::sleep(Duration::from_secs(5)).await;
            }
        }
    }
}
