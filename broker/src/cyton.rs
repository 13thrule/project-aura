//! Cyton acquisition via BrainFlow.
//!
//! Per CLAUDE.md: use BrainFlow's Rust bindings (BoardShim over the
//! Cyton board id) rather than hand-rolling the Cyton's serial packet
//! framing — BrainFlow already solves that, including the retry/error
//! handling around dropped bytes that design doc section 7 risk 2 is
//! worried about.
//!
//! NOT compiled or run in this environment — there is no crate literally
//! named `brainflow` on crates.io (confirmed via the crates.io API: 404,
//! not just a version mismatch). BrainFlow's Rust binding requires
//! building the BrainFlow C/C++ core locally, then building the Rust
//! binding against it (see broker/README.md and
//! https://brainflow.readthedocs.io/en/stable/BuildBrainFlow.html#rust).
//! Once that local build exists, path/git-dependency it in Cargo.toml
//! (the commented line is already there) and this file should compile
//! close to as-is — the shape below mirrors BrainFlow's documented
//! cross-language API (BoardShim::prepare_session /start_stream
//! /get_board_data_count /get_current_board_data), which is consistent
//! across its Python/Java/C++ bindings, so it's a reasonable bet even
//! unverified here. Confirm the exact Rust method names/signatures
//! against your locally-built binding before trusting this blindly.

use std::time::SystemTime;

// use crate::AuraEvent; // needed once the commented run() below is activated

#[derive(Debug, Clone)]
pub struct Sample {
    pub host_received_at: SystemTime,
    pub channels: [f32; 8],
    pub accel: [f32; 3],
}

// use brainflow::{
//     board_shim::{BoardIds, BoardShim},
//     brainflow_input_params::BrainFlowInputParamsBuilder,
// };
//
// pub async fn run(
//     serial_port: &str,
//     tx: tokio::sync::broadcast::Sender<AuraEvent>,
// ) -> anyhow::Result<()> {
//     brainflow::board_shim::enable_dev_board_logger()?;
//
//     let board_id = BoardIds::CytonBoard as i32;
//     let mut params = BrainFlowInputParamsBuilder::default().build();
//     params.serial_port = serial_port.to_string();
//
//     let board = BoardShim::new(board_id, params)?;
//     board.prepare_session()?;
//     board.start_stream(45000, "")?;
//
//     // EEG/accel row indices are board-specific — ask BrainFlow rather
//     // than hardcoding Cyton's layout, so this doesn't silently break if
//     // the board id changes (e.g. to the synthetic board for testing).
//     let eeg_rows = BoardShim::get_eeg_channels(board_id)?;
//     let accel_rows = BoardShim::get_accel_channels(board_id)?;
//     anyhow::ensure!(eeg_rows.len() == 8, "expected 8 EEG channels for Cyton");
//     anyhow::ensure!(accel_rows.len() == 3, "expected 3 accelerometer channels");
//
//     // 100ms poll interval -> ~25 samples/poll at 250Hz. Soak-test this
//     // under real load before trusting it overnight (design doc risk 2)
//     // — a poll interval too slow risks the board's internal ring buffer
//     // overflowing before we drain it.
//     let mut poll = tokio::time::interval(Duration::from_millis(100));
//
//     loop {
//         poll.tick().await;
//         let count = board.get_board_data_count(None)?;
//         if count == 0 {
//             continue;
//         }
//         let data = board.get_current_board_data(count, None)?; // rows x count
//         let host_received_at = SystemTime::now();
//
//         for col in 0..count {
//             let mut channels = [0.0f32; 8];
//             for (i, &row) in eeg_rows.iter().enumerate() {
//                 channels[i] = data[row][col] as f32;
//             }
//             let mut accel = [0.0f32; 3];
//             for (i, &row) in accel_rows.iter().enumerate() {
//                 accel[i] = data[row][col] as f32;
//             }
//             let _ = tx.send(AuraEvent::Sample(Sample { host_received_at, channels, accel }));
//         }
//     }
// }
