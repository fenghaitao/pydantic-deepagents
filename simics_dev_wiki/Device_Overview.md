# dmr_imh_hwrs_fv — Device Overview

#### Introduction
The dmr_imh_hwrs_fv Simics model implements an IMH (Integrated Memory Hub) Hardware Reset Sequencer (HWRS) functional model used on DMR-class platforms. The model represents the HWRS Gen2 IMH hardware IP that coordinates power sequencing, boot/reset sequencing, IP-disable/fuse sampling, die topology/provisioning straps, clock/reference readiness, PCIe/IO reset routing (including CNIC-specific flows), thermal trip handling, and debug/early-boot handshakes.

Simulation scope
- Modeled (functional and behavioral):
  - MMIO register bank (sb_cr) with read/write semantics, resolved read callbacks (fuse/strap resolution), and register side-effects used by firmware/software.
  - Reset sequence FSM (reset_seq_fsm), sequencer step execution and programmable command table behaviour.
  - Power-good and reset output drives: many active-low reset/power-good outputs and die enable pins with timing and sequencing controlled by attributes and sequencer commands.
  - Fuse/strap sampling and resolved register outputs (IP_DISABLE fuses, POC_STRAPS, board/sku straps).
  - Clock/reference readiness and reference clock gating / RCLK programming handshake semantics.
  - Thermal-trip input and firmware-controlled thermal-trip output.
  - Integration signals: IMH↔IMH and IMH↔CBB handshake requests/acknowledgements, SCU configuration handshakes, Q-channel power-management signals, PLTRST/CPUPWRGD semantics.
  - Hardware-timed behaviors via events (infra_timer, reset_sequencer_event) to model deferred actions and timeouts.
  - Configurable timeouts and strap-backed attributes to govern sequencing delays and decision logic.
- Stubbed / simplified:
  - Detailed electrical analog behaviour of power rails — modeled as boolean power-good/isolation signals rather than analog voltages.
  - Detailed per-IP internal microarchitectures — model exposes reset/power-good control only.
  - Any vendor-specific scan/BIST physical implementations; BIST is exposed only via strap/config bits.
  - Cycle-accurate timing of internal clocks — timers are coarse-grain microsecond-level for sequencing, not cycle-accurate clocks.

This device provides firmware-visible behaviour sufficient for platform bring-up, firmware validation, and system-level integration tests in Simics.

#### Device Architecture Diagram
```mermaid
flowchart TD
    dmr_imh_hwrs_fv[dmr_imh_hwrs_fv]
    bank_sb_cr["sb_cr (119 regs)"]
    dmr_imh_hwrs_fv --> bank_sb_cr
    bank_reset_seq_fsm["reset_seq_fsm (8 regs)"]
    dmr_imh_hwrs_fv --> bank_reset_seq_fsm
    evt_infra_timer>infra_timer]
    dmr_imh_hwrs_fv -.-> evt_infra_timer
    evt_reset_sequencer_event>reset_sequencer_event]
    dmr_imh_hwrs_fv -.-> evt_reset_sequencer_event
    port_fusectrl_early_boot_done[/fusectrl_early_boot_done/]
    port_fusectrl_early_boot_done -->|PORT| dmr_imh_hwrs_fv
    port_rclk_ip_ready[/rclk_ip_ready/]
    port_rclk_ip_ready -->|PORT| dmr_imh_hwrs_fv
    port_s5_early_boot_done[/s5_early_boot_done/]
    port_s5_early_boot_done -->|PORT| dmr_imh_hwrs_fv
    port_mdfc_ip_ready[/mdfc_ip_ready/]
    port_mdfc_ip_ready -->|PORT| dmr_imh_hwrs_fv
    port_imh2imh_hwsync_req_in[/imh2imh_hwsync_req_in/]
    port_imh2imh_hwsync_req_in -->|PORT| dmr_imh_hwrs_fv
    port_thermtrip_in[/thermtrip_in/]
    port_thermtrip_in -->|PORT| dmr_imh_hwrs_fv
    port_endebug_early_boot_done[/endebug_early_boot_done/]
    port_endebug_early_boot_done -->|PORT| dmr_imh_hwrs_fv
    port_GLOBAL_RESET_N[/GLOBAL_RESET_N/]
    port_GLOBAL_RESET_N -->|PORT| dmr_imh_hwrs_fv
    port_hwrs_mc_sr_ack[/hwrs_mc_sr_ack/]
    port_hwrs_mc_sr_ack -->|PORT| dmr_imh_hwrs_fv
    port_s3m_rclk_programming_done[/s3m_rclk_programming_done/]
    port_s3m_rclk_programming_done -->|PORT| dmr_imh_hwrs_fv
    port_AUX_PWRGOOD[/AUX_PWRGOOD/]
    port_AUX_PWRGOOD -->|PORT| dmr_imh_hwrs_fv
    port_puf_ip_ready[/puf_ip_ready/]
    port_puf_ip_ready -->|PORT| dmr_imh_hwrs_fv
    port_early_boot_debug_exit[/early_boot_debug_exit/]
    port_early_boot_debug_exit -->|PORT| dmr_imh_hwrs_fv
    port_cro_clk_valid[/cro_clk_valid/]
    port_cro_clk_valid -->|PORT| dmr_imh_hwrs_fv
    port_scu_pmsync_done[/scu_pmsync_done/]
    port_scu_pmsync_done -->|PORT| dmr_imh_hwrs_fv
    port_s0_late_boot_done[/s0_late_boot_done/]
    port_s0_late_boot_done -->|PORT| dmr_imh_hwrs_fv
    port_nac_fw_loader_done[/nac_fw_loader_done/]
    port_nac_fw_loader_done -->|PORT| dmr_imh_hwrs_fv
    port_imh2cbb_hwsync_req_in[/imh2cbb_hwsync_req_in/]
    port_imh2cbb_hwsync_req_in -->|PORT| dmr_imh_hwrs_fv
    port_fdfx_powergood_rst_b[/fdfx_powergood_rst_b/]
    port_fdfx_powergood_rst_b -->|PORT| dmr_imh_hwrs_fv
    port_s0_early_boot_done[/s0_early_boot_done/]
    port_s0_early_boot_done -->|PORT| dmr_imh_hwrs_fv
    port_dfxa_early_boot_done[/dfxa_early_boot_done/]
    port_dfxa_early_boot_done -->|PORT| dmr_imh_hwrs_fv
    port_imh2imh_hwsync_ack_in[/imh2imh_hwsync_ack_in/]
    port_imh2imh_hwsync_ack_in -->|PORT| dmr_imh_hwrs_fv
    port_scu_config_ack[/scu_config_ack/]
    port_scu_config_ack -->|PORT| dmr_imh_hwrs_fv
    port_nac_ready_for_enum[/nac_ready_for_enum/]
    port_nac_ready_for_enum -->|PORT| dmr_imh_hwrs_fv
    port_nac_mini_loader_done[/nac_mini_loader_done/]
    port_nac_mini_loader_done -->|PORT| dmr_imh_hwrs_fv
    port_hwrs_s0_break[/hwrs_s0_break/]
    port_hwrs_s0_break -->|PORT| dmr_imh_hwrs_fv
    port_s3m_early_comm_ready[/s3m_early_comm_ready/]
    port_s3m_early_comm_ready -->|PORT| dmr_imh_hwrs_fv
    port_imh2cbb_hwsync_ack_in[/imh2cbb_hwsync_ack_in/]
    port_imh2cbb_hwsync_ack_in -->|PORT| dmr_imh_hwrs_fv
    port_nac_soc_qch_accept[/nac_soc_qch_accept/]
    port_nac_soc_qch_accept -->|PORT| dmr_imh_hwrs_fv
    port_ext_spare_pin0[/ext_spare_pin0/]
    port_ext_spare_pin0 -->|PORT| dmr_imh_hwrs_fv
    port_hwrs_s0_release_toggle[/hwrs_s0_release_toggle/]
    port_hwrs_s0_release_toggle -->|PORT| dmr_imh_hwrs_fv
    port_hwrs_dummy_test[/hwrs_dummy_test/]
    port_hwrs_dummy_test -->|PORT| dmr_imh_hwrs_fv
    port_PLTRST[/PLTRST/]
    port_PLTRST -->|PORT| dmr_imh_hwrs_fv
    port_s3m_late_comm_ready[/s3m_late_comm_ready/]
    port_s3m_late_comm_ready -->|PORT| dmr_imh_hwrs_fv
    port_bpk_early_boot_done[/bpk_early_boot_done/]
    port_bpk_early_boot_done -->|PORT| dmr_imh_hwrs_fv
    port_CPUPWRGD[/CPUPWRGD/]
    port_CPUPWRGD -->|PORT| dmr_imh_hwrs_fv
    port_pmax_ip_ready[/pmax_ip_ready/]
    port_pmax_ip_ready -->|PORT| dmr_imh_hwrs_fv
    port_S0_PWR_OK[/S0_PWR_OK/]
    port_S0_PWR_OK -->|PORT| dmr_imh_hwrs_fv
    conn_nac_sn2sfi_rst_n[\nac_sn2sfi_rst_n\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_nac_sn2sfi_rst_n
    conn_vnn_soc_group_side_rst_b[\vnn_soc_group_side_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_vnn_soc_group_side_rst_b
    conn_bpk_early_boot_side_rst_b[\bpk_early_boot_side_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_bpk_early_boot_side_rst_b
    conn_puf_rst_b[\puf_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_puf_rst_b
    conn_s3m_early_boot_side_rst_b[\s3m_early_boot_side_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_s3m_early_boot_side_rst_b
    conn_soc_infra_sb_rst_b[\soc_infra_sb_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_soc_infra_sb_rst_b
    conn_vin_pwrgood_rst_b[\vin_pwrgood_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_vin_pwrgood_rst_b
    conn_nac_hif_pcie0_perst_n0[\nac_hif_pcie0_perst_n0\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_nac_hif_pcie0_perst_n0
    conn_s3m_late_comm_open[\s3m_late_comm_open\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_s3m_late_comm_open
    conn_imh2imh_hwsync_req_out[\imh2imh_hwsync_req_out\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_imh2imh_hwsync_req_out
    conn_scu_start_pmsync_handshake[\scu_start_pmsync_handshake\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_scu_start_pmsync_handshake
    conn_nac_early_boot_rst_b[\nac_early_boot_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_nac_early_boot_rst_b
    conn_hwrs_mc_sr_req[\hwrs_mc_sr_req\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_hwrs_mc_sr_req
    conn_nac_inf_rstbus_rst_b[\nac_inf_rstbus_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_nac_inf_rstbus_rst_b
    conn_nac_ss_qreqn[\nac_ss_qreqn\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_nac_ss_qreqn
    conn_punit_pm_unwind[\punit_pm_unwind\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_punit_pm_unwind
    conn_imh2cbb_hwsync_req_out[\imh2cbb_hwsync_req_out\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_imh2cbb_hwsync_req_out
    conn_nac_pwrgood_rst_b[\nac_pwrgood_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_nac_pwrgood_rst_b
    conn_cnic_s0_pwr_ok_int[\cnic_s0_pwr_ok_int\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_cnic_s0_pwr_ok_int
    conn_nac_sys_rst_n[\nac_sys_rst_n\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_nac_sys_rst_n
    conn_nac_inf_iosfsb_rst_b[\nac_inf_iosfsb_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_nac_inf_iosfsb_rst_b
    conn_reset_bus_dev[\reset_bus_dev\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_reset_bus_dev
    conn_vref_pwrgood_rst_b[\vref_pwrgood_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_vref_pwrgood_rst_b
    conn_scu_uc_rst_b[\scu_uc_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_scu_uc_rst_b
    conn_yyDIE_ENABLE3[\yyDIE_ENABLE3\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_yyDIE_ENABLE3
    conn_puf_side_rst_b[\puf_side_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_puf_side_rst_b
    conn_scu_config_done[\scu_config_done\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_scu_config_done
    conn_nac_sn2sfi_rst_pre_ind_n[\nac_sn2sfi_rst_pre_ind_n\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_nac_sn2sfi_rst_pre_ind_n
    conn_scu_config_req[\scu_config_req\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_scu_config_req
    conn_soc_pwrgood_rst_b[\soc_pwrgood_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_soc_pwrgood_rst_b
    conn_dfxa_early_boot_side_rst_b[\dfxa_early_boot_side_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_dfxa_early_boot_side_rst_b
    conn_infra_side_rst_b[\infra_side_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_infra_side_rst_b
    conn_yyDIE_ENABLE2[\yyDIE_ENABLE2\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_yyDIE_ENABLE2
    conn_vnn_soc_group_pwrgood_rst_b[\vnn_soc_group_pwrgood_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_vnn_soc_group_pwrgood_rst_b
    conn_vinf_iso_b[\vinf_iso_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_vinf_iso_b
    conn_imh2imh_hwsync_ack_out[\imh2imh_hwsync_ack_out\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_imh2imh_hwsync_ack_out
    conn_rclk_config[\rclk_config\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_rclk_config
    conn_hwrs_set_warm_reset_preamble_run[\hwrs_set_warm_reset_preamble_run\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_hwrs_set_warm_reset_preamble_run
    conn_soc_side_rst_b[\soc_side_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_soc_side_rst_b
    conn_vinf_pwrgood_rst_b[\vinf_pwrgood_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_vinf_pwrgood_rst_b
    conn_early_boot_side_rst_b[\early_boot_side_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_early_boot_side_rst_b
    conn_yyDIE_ENABLE1[\yyDIE_ENABLE1\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_yyDIE_ENABLE1
    conn_vin_iso_b[\vin_iso_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_vin_iso_b
    conn_early_boot_prim_rst_b[\early_boot_prim_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_early_boot_prim_rst_b
    conn_vnn_early_boot_done_to_s3[\vnn_early_boot_done_to_s3\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_vnn_early_boot_done_to_s3
    conn_hwrs_mc_pstate[\hwrs_mc_pstate\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_hwrs_mc_pstate
    conn_s3m_rclk_boot_done[\s3m_rclk_boot_done\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_s3m_rclk_boot_done
    conn_sblink_bringup[\sblink_bringup\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_sblink_bringup
    conn_THERMAL_TRIP_OUT[\THERMAL_TRIP_OUT\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_THERMAL_TRIP_OUT
    conn_xxREFCLK_Rdy[\xxREFCLK_Rdy\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_xxREFCLK_Rdy
    conn_yyDIE_ENABLE0[\yyDIE_ENABLE0\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_yyDIE_ENABLE0
    conn_scu_early_boot_pwrgood_rst_b[\scu_early_boot_pwrgood_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_scu_early_boot_pwrgood_rst_b
    conn_vref_iso_b[\vref_iso_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_vref_iso_b
    conn_imh2cbb_hwsync_ack_out[\imh2cbb_hwsync_ack_out\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_imh2cbb_hwsync_ack_out
    conn_s3m_early_comm_open[\s3m_early_comm_open\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_s3m_early_comm_open
    conn_endebug_early_boot_side_rst_b[\endebug_early_boot_side_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_endebug_early_boot_side_rst_b
    conn_soc_early_infra_sb_rst_b[\soc_early_infra_sb_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_soc_early_infra_sb_rst_b
    conn_early_boot_pwrgood_rst_b[\early_boot_pwrgood_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_early_boot_pwrgood_rst_b
    conn_fusectrl_early_boot_side_rst_b[\fusectrl_early_boot_side_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_fusectrl_early_boot_side_rst_b
    conn_vnn_infra_fabric_rst_b[\vnn_infra_fabric_rst_b\]
    dmr_imh_hwrs_fv -->|CONNECT| conn_vnn_infra_fabric_rst_b
```

#### System Architecture

How software interacts with the device (MMIO)
- The sb_cr register bank (119 registers) is the firmware/OS-visible MMIO interface used to:
  - Read fused/strap-resolved registers (read-callbacks may compute resolved values).
  - Program sequencer control registers (reset_seq_fsm.*, command table pointers, enable/disable features).
  - Read status bits for power-good, sequencer step, and feature availability.
  - Trigger actions (e.g., start warm reset preamble, request sequencer run) via write-to-clear or write-to-set registers.
- The reset_seq_fsm register bank exposes the sequencer step counter, control flags and command execution controls; firmware advances or inspects the step counter and programs the command table via sb_cr.

How inputs (PORT signals) affect internal state
- PORT inputs represent external hardware signals and upstream IP readiness. Examples:
  - rclk_ip_ready, puf_ip_ready, mdfc_ip_ready, pmax_ip_ready: when asserted they mark respective IP readiness; sequencer logic and power sequencing consult these to progress.
  - PLTRST, GLOBAL_RESET_N, CPUPWRGD, AUX_PWRGOOD, S0_PWR_OK: platform/global reset or power-good inputs that drive global state transitions and influence sequence entry/exit.
  - thermtrip_in: sets an internal thermal trip state (pseudo attribute) and triggers THERMAL_TRIP_OUT when asserted; setter converts to modelled behaviour immediately.
  - imh2imh_hwsync_req_in / imh2cbb_hwsync_req_in and *_ack_in: synchronization requests from peer IMH/CBB dies; they feed the inter-die handshake state machine used during multi-die bring-up.
  - s3m_rclk_programming_done, scu_pmsync_done, scu_config_ack: handshake/ack signals for SCU/RCLK/PM actions; used by sequencer to wait for completion steps.
  - early-boot debug signals, fusectrl_early_boot_done, bpk_early_boot_done, etc.: coordinate early-boot phase transitions.
- Ports update device attributes/flags and can schedule sequencer progression or interrupt pending timeouts.

How device state changes drive outputs (CONNECT)
- Outputs are driven as boolean signals derived from current strap/config state, sequencer state, and runtime inputs:
  - Reset/power outputs (nac_sys_rst_n, nac_early_boot_rst_b, soc_pwrgood_rst_b, vinf_pwrgood_rst_b, infra_side_rst_b, etc.) change state when preconditions are met (power-good assertions, timeouts, sequencer steps).
  - Handshake outputs (imh2imh_hwsync_req_out, imh2imh_hwsync_ack_out, imh2cbb_hwsync_req_out/ack_out) mirror internal inter-die handshake state.
  - THERMAL_TRIP_OUT mirrors internal thermal-trip state and may be asserted by firmware via attribute or in response to thermtrip_in.
  - rclk_config, xxREFCLK_Rdy, s3m_rclk_boot_done represent clock/ref and RCLK programming status to other components.
  - hwrs_mc_sr_req, hwrs_mc_sr_ack (ack is input) implement requests to memory controller subsystem for state transitions; punit_pm_unwind and related outputs drive power-management sequencing.

How FSMs orchestrate state-dependent behavior
- The model uses an explicit reset sequence FSM (reset_seq_fsm) register bank combined with a sequencer engine:
  - A software-visible step counter (reset_seq_fsm.reset_seq_step) indexes a programmable command table (stored in sb_cr registers). When a step is executed the model performs deterministic side-effect actions (drive resets, wait on inputs, set timers).
  - Sequencer runs are time-managed; steps can request waits for specific inputs/handshakes or timers, and may update MMIO-visible status.
  - No other named FSMs are included; complex behaviours are implemented in C/Python model code reacting to sequencer state and inputs.

How events model hardware timers and deferred actions
- infra_timer: manages periodic infrastructure timers and housekeeping actions (e.g., long timeouts, monitoring).
- reset_sequencer_event: scheduled to trigger execution of the next reset sequence step after specified delay; models hardware timing of sequencer step durations, preambles, and inter-step delays.
- Events enable realistic microsecond-level delays and timeouts (attributes such as d2d_timeout_us, preamble_timeout_us, didt_timeout_us, unwind_timeout_us).

Clock and reset domain overview (inferred)
- Clock/reference domain signals:
  - cro_clk_valid, xxREFCLK_Rdy, rclk_config, s3m_rclk_boot_done: indicate reference clocks and RCLK programming/valid status.
  - VINx and VREF-related signals (vinf_iso_b, vref_iso_b, vin_iso_b, vinf_pwrgood_rst_b, vref_pwrgood_rst_b) model power domain isolation and power-good boundaries.
- Reset domains:
  - Platform/global resets: PLTRST, GLOBAL_RESET_N control global reset domains and feed into HWRS logic.
  - IO/PCIe domain resets: nac_hif_pcie0_perst_n0, nac_sys_rst_n, nac_inf_iosfsb_rst_b etc.
  - Early-boot, infra, SOC, die-enable resets: early_boot_*, infra_side_rst_b, soc_side_rst_b, yyDIE_ENABLEn signals.
- The model represents domains as boolean signals with interdependencies controlled by sequencer rules and strap/config attributes.

#### Main Hardware Features
- hardware-reset-sequencer: Implements HWRS sequencing engine and software-visible sequencer control.
- power-sequencing-and-power-good: Models power-good logic and drives power-good reset outputs across domains.
- boot-and-initialization-sequencing: Supports early-boot signalling, phase transitions and firmware coordination.
- fuse-and-strap-configuration: Samples fuse/strap attributes and exposes resolved registers.
- die-topology-and-die-synchronization: Handles IMH/CBB inter-die handshakes and die identifier/enable signalling.
- ip-feature-control: Resolves IP_DISABLE fuses and exposes feature gating behavior.
- clock-and-reference-control: Models RCLK programming, reference-clock readiness and related outputs.
- pcie-and-io-reset: Implements PCIe and IO reset sequencing, including CNIC routing specifics.
- device-identification-and-provisioning: Exposes board_id, strap_socket_id, partition id and SKU provisioning behavior.
- thermal-and-safety: Thermal-trip input/outputs and safety-driven reset/power behavior.
- pin-and-signal-drive: Read-only resolved registers and side-effectful write behavior for pin/signal control.
- debug-and-integration: Early-boot debug exits, handshakes and SCU/PM sync interfaces for integration testing.
- sequencer-control-and-timing: Timer-driven sequencer execution with configurable microsecond timeouts.
- security-and-trust-configuration: Exposes limited trust/security strap readouts and resolved security-related registers.

#### Documentation Index
| Page | Description | Audience |
|------|-------------|---------|
| [Capability: hardware-reset-sequencer](capabilities/hardware-reset-sequencer.md) | This Simics model implements a Hardware Reset Sequencer (HWRS) functional model that drives many active-low reset and po | Developer / Validator / Architect |
| [Capability: power-sequencing-and-power-good](capabilities/power-sequencing-and-power-good.md) | This Simics model implements a substantial portion of the HWRS power-sequencing and power-good domain for the dmr_imh_hw | Developer / Validator / Architect |
| [Capability: boot-and-initialization-sequencing](capabilities/boot-and-initialization-sequencing.md) | This Simics model implements the dmr_imh_hwrs_fv device's boot-and-initialization sequencing logic for early-boot coordi | Developer / Validator / Architect |
| [Capability: fuse-and-strap-configuration](capabilities/fuse-and-strap-configuration.md) | The dmr_imh_hwrs_fv Simics model implements fuse-and-strap sampling and resolved-strap register readouts plus a set of e | Developer / Validator / Architect |
| [Capability: die-topology-and-die-synchronization](capabilities/die-topology-and-die-synchronization.md) | This Simics model (dmr_imh_hwrs_fv) implements IMH hardware-reset and die-topology/synchronization behaviors as code: it | Developer / Validator / Architect |
| [Capability: ip-feature-control](capabilities/ip-feature-control.md) | This Simics model implements HWRS IP-disable and reset/feature-control behavior for the dmr_imh_hwrs_fv device. It expos | Developer / Validator / Architect |
| [Capability: clock-and-reference-control](capabilities/clock-and-reference-control.md) | This Simics model implements the HWRS clock-and-reference control behavior that exposes reference-clock configuration an | Developer / Validator / Architect |
| [Capability: pcie-and-io-reset](capabilities/pcie-and-io-reset.md) | The dmr_imh_hwrs_fv Simics model implements PCIe and IO reset sequencing and CNIC-specific reset routing for the IMH/HWR | Developer / Validator / Architect |
| [Capability: device-identification-and-provisioning](capabilities/device-identification-and-provisioning.md) | The dmr_imh_hwrs_fv Simics model implements board/sku provisioning and readout by exposing strap-backed configuration at | Developer / Validator / Architect |
| [Capability: thermal-and-safety](capabilities/thermal-and-safety.md) | The Simics model for dmr_imh_hwrs_fv implements a thermal-trip input and a firmware-controlled thermal-trip output: the  | Developer / Validator / Architect |
| [Capability: pin-and-signal-drive](capabilities/pin-and-signal-drive.md) | This Simics model implements two read-only “resolved” IP-disable registers (sb_cr.IP_DISABLE_RESOLVED_CR_DWORD0 and sb_c | Developer / Validator / Architect |
| [Capability: debug-and-integration](capabilities/debug-and-integration.md) | This Simics model implements the HWRS "debug-and-integration" behavior that manages early-boot debug/external handshakes | Developer / Validator / Architect |
| [Capability: sequencer-control-and-timing](capabilities/sequencer-control-and-timing.md) | The Simics model implements the DMR/IMH hardware reset sequencer behaviour: a software-visible step counter (reset_seq_f | Developer / Validator / Architect |
| [Capability: security-and-trust-configuration](capabilities/security-and-trust-configuration.md) | The dmr_imh_hwrs_fv Simics model implements a limited set of security-and-trust configuration behaviors: it exposes a re | Developer / Validator / Architect |

#### Interface Summary
(PORT = IN, CONNECT = OUT. Connected Component inferred from signal name.)

| Signal Name | Direction | Interface Type | Connected Component | Purpose |
|-------------|-----------|----------------|---------------------|---------|
| fusectrl_early_boot_done | IN | PORT | Fuse controller | Early-boot completion from fuse controller |
| rclk_ip_ready | IN | PORT | RCLK controller / clock IP | Indicates reference clock IP is ready |
| s5_early_boot_done | IN | PORT | System power controller | Early-boot done in S5 domain |
| mdfc_ip_ready | IN | PORT | MDFC IP | MDFC readiness flag |
| imh2imh_hwsync_req_in | IN | PORT | Peer IMH | Incoming IMH HW sync request |
| thermtrip_in | IN | PORT | Thermal sensor / motherboard | External thermal trip input |
| endebug_early_boot_done | IN | PORT | External debug module | Early-boot debug done |
| GLOBAL_RESET_N | IN | PORT | Platform reset | Global active-low reset input |
| hwrs_mc_sr_ack | IN | PORT | Memory controller | Ack for HWRS MC service request |
| s3m_rclk_programming_done | IN | PORT | S3M/RCLK manager | RCLK programming done |
| AUX_PWRGOOD | IN | PORT | AUX power rail | AUX power-good input |
| puf_ip_ready | IN | PORT | PUF (security) | PUF readiness |
| early_boot_debug_exit | IN | PORT | Debug subsystem | Early debug exit signal |
| cro_clk_valid | IN | PORT | CRO clock domain | CRO clock validity |
| scu_pmsync_done | IN | PORT | SCU | SCU PMSYNC completion |
| s0_late_boot_done | IN | PORT | S0 boot controller | Late boot done in S0 |
| nac_fw_loader_done | IN | PORT | NAC firmware loader | NAC FW loader completion |
| imh2cbb_hwsync_req_in | IN | PORT | Attached CBB | Incoming CBB HW sync request |
| fdfx_powergood_rst_b | IN | PORT | FDFX power-good | FDFX domain power-good/reset |
| s0_early_boot_done | IN | PORT | S0 boot controller | Early boot done in S0 |
| dfxa_early_boot_done | IN | PORT | DFXA domain | DFXA early boot done |
| imh2imh_hwsync_ack_in | IN | PORT | Peer IMH | IMH HW sync ack in |
| scu_config_ack | IN | PORT | SCU | SCU config acknowledge |
| nac_ready_for_enum | IN | PORT | NAC subsystem | NAC ready-for-enumeration |
| nac_mini_loader_done | IN | PORT | NAC mini-loader | NAC mini-loader done |
| hwrs_s0_break | IN | PORT | Platform test/harness | S0 break toggle input |
| s3m_early_comm_ready | IN | PORT | S3M communication | Early comm ready for S3M |
| imh2cbb_hwsync_ack_in | IN | PORT | Attached CBB | CBB HW sync ack in |
| nac_soc_qch_accept | IN | PORT | NAC/SOC QCH | Q-channel accept notification |
| ext_spare_pin0 | IN | PORT | External spare | Spare/aux external input |
| hwrs_s0_release_toggle | IN | PORT | Platform test/harness | Toggle to release S0 hold |
| hwrs_dummy_test | IN | PORT | Test harness | Dummy test input |
| PLTRST | IN | PORT | Platform reset | Platform reset assertion |
| s3m_late_comm_ready | IN | PORT | S3M communication | Late comm ready for S3M |
| bpk_early_boot_done | IN | PORT | BPK block | Early boot done from BPK |
| CPUPWRGD | IN | PORT | CPU power domain | CPU power-good input |
| pmax_ip_ready | IN | PORT | PMAX IP | PMAX readiness |
| S0_PWR_OK | IN | PORT | Power controller | S0 power OK indicator |
| nac_sn2sfi_rst_n | OUT | CONNECT | NAC / SN2SFI bridge | NAC SN2SFI reset (active low) |
| vnn_soc_group_side_rst_b | OUT | CONNECT | VNN SOC group | Group-side reset for VNN SOC |
| bpk_early_boot_side_rst_b | OUT | CONNECT | BPK | Early-boot side reset for BPK |
| puf_rst_b | OUT | CONNECT | PUF | Reset for PUF domain |
| s3m_early_boot_side_rst_b | OUT | CONNECT | S3M | Early-boot side reset for S3M |
| soc_infra_sb_rst_b | OUT | CONNECT | SOC infra | SOC infra subsystem reset |
| vin_pwrgood_rst_b | OUT | CONNECT | VIN domain | VIN power-good reset output |
| nac_hif_pcie0_perst_n0 | OUT | CONNECT | NAC / PCIe | PCIe PERST# for NAC HIF |
| s3m_late_comm_open | OUT | CONNECT | S3M comm | Open late communication channel |
| imh2imh_hwsync_req_out | OUT | CONNECT | Peer IMH | IMH HW sync request out |
| scu_start_pmsync_handshake | OUT | CONNECT | SCU | Start PMSYNC handshake |
| nac_early_boot_rst_b | OUT | CONNECT | NAC | NAC early-boot reset |
| hwrs_mc_sr_req | OUT | CONNECT | Memory controller | HWRS service request to MC |
| nac_inf_rstbus_rst_b | OUT | CONNECT | NAC infrastructure | NAC infra reset bus control |
| nac_ss_qreqn | OUT | CONNECT | NAC subsystem | NAC Q-request signal |
| punit_pm_unwind | OUT | CONNECT | PUnit | Trigger PM unwind sequence |
| imh2cbb_hwsync_req_out | OUT | CONNECT | Attached CBB | CBB HW sync request out |
| nac_pwrgood_rst_b | OUT | CONNECT | NAC | NAC power-good reset |
| cnic_s0_pwr_ok_int | OUT | CONNECT | CNIC | CNIC S0 power OK interrupt |
| nac_sys_rst_n | OUT | CONNECT | NAC | NAC system reset (active low) |
| nac_inf_iosfsb_rst_b | OUT | CONNECT | NAC IOSFSB | NAC IOSFSB reset |
| reset_bus_dev | OUT | CONNECT | Reset bus | Device-level reset bus indication |
| vref_pwrgood_rst_b | OUT | CONNECT | VREF domain | VREF power-good reset |
| scu_uc_rst_b | OUT | CONNECT | SCU | SCU microcontroller reset |
| yyDIE_ENABLE3 | OUT | CONNECT | Die enable group | Die-enable pin group 3 |
| puf_side_rst_b | OUT | CONNECT | PUF | PUF-side reset |
| scu_config_done | OUT | CONNECT | SCU | SCU config completion indicator |
| nac_sn2sfi_rst_pre_ind_n | OUT | CONNECT | NAC / SN2SFI bridge | Pre-indicator for sn2sfi reset |
| scu_config_req | OUT | CONNECT | SCU | Request SCU config |
| soc_pwrgood_rst_b | OUT | CONNECT | SOC | SOC power-good reset |
| dfxa_early_boot_side_rst_b | OUT | CONNECT | DFXA | DFXA early-boot reset |
| infra_side_rst_b | OUT | CONNECT | Infrastructure | Infra-side reset |
| yyDIE_ENABLE2 | OUT | CONNECT | Die enable group | Die-enable pin group 2 |
| vnn_soc_group_pwrgood_rst_b | OUT | CONNECT | VNN SOC group | VNN SOC group power-good |
| vinf_iso_b | OUT | CONNECT | VINF isolation | VINF isolation control |
| imh2imh_hwsync_ack_out | OUT | CONNECT | Peer IMH | IMH HW sync ack out |
| rclk_config | OUT | CONNECT | RCLK config port | RCLK configuration/command |
| hwrs_set_warm_reset_preamble_run | OUT | CONNECT | HWRS sequencer | Signal to set warm reset preamble run |
| soc_side_rst_b | OUT | CONNECT | SOC | SOC-side reset |
| vinf_pwrgood_rst_b | OUT | CONNECT | VINF | VINF power-good reset |
| early_boot_side_rst_b | OUT | CONNECT | Early-boot | Early-boot side reset |
| yyDIE_ENABLE1 | OUT | CONNECT | Die enable group | Die-enable pin group 1 |
| vin_iso_b | OUT | CONNECT | VIN isolation | VIN isolation control |
| early_boot_prim_rst_b | OUT | CONNECT | Early-boot primary | Primary early-boot reset |
| vnn_early_boot_done_to_s3 | OUT | CONNECT | VNN domain | Early-boot done propagation to S3 domain |
| hwrs_mc_pstate | OUT | CONNECT | Memory controller | HWRS memory controller power-state info |
| s3m_rclk_boot_done | OUT | CONNECT | S3M / RCLK | Notifies RCLK boot completion |
| sblink_bringup | OUT | CONNECT | SBL | SBL bringup indicator |
| THERMAL_TRIP_OUT | OUT | CONNECT | System thermal interface | Thermal trip output driven by model |
| xxREFCLK_Rdy | OUT | CONNECT | Reference clock consumers | Reference clock ready indicator |
| yyDIE_ENABLE0 | OUT | CONNECT | Die enable group | Die-enable pin group 0 |
| scu_early_boot_pwrgood_rst_b | OUT | CONNECT | SCU | Early-boot power-good reset for SCU |
| vref_iso_b | OUT | CONNECT | VREF isolation | VREF isolation control |
| imh2cbb_hwsync_ack_out | OUT | CONNECT | Attached CBB | CBB HW sync ack out |
| s3m_early_comm_open | OUT | CONNECT | S3M comm | Open early communication channel |
| endebug_early_boot_side_rst_b | OUT | CONNECT | Endebug | Endebug early-boot reset |
| soc_early_infra_sb_rst_b | OUT | CONNECT | SOC infra | Early infra side reset for SOC |
| early_boot_pwrgood_rst_b | OUT | CONNECT | Early-boot | Early-boot power-good reset |
| fusectrl_early_boot_side_rst_b | OUT | CONNECT | Fuse controller | Fusectrl early-boot side reset |
| vnn_infra_fabric_rst_b | OUT | CONNECT | VNN infra fabric | VNN infra fabric reset |

#### Register Bank Summary
| Bank | Register Count | Functional Purpose | Key Registers |
|------|---------------:|--------------------|---------------|
| sb_cr | 119 | Backend MMIO control/status register bank. Exposes fuse/strap resolved values, IP-disable registers, POC_STRAPS, board/sku straps, reset command table and many side-effectful control bits. | IP_DISABLE_RESOLVED_CR_DWORD0, IP_DISABLE_RESOLVED_CR_DWORD3, POC_STRAPS, SKU_FEATURE_DWORDx, board_id0..4, hwrs_final_die_id, various reset command table registers |
| reset_seq_fsm | 8 | Reset sequence finite-state machine control/status. Controls sequencer progression, step counter and basic sequencer control flags used to run/program the reset sequence. | reset_seq_step, reset_seq_control, per-step status/condition registers |

#### How to Use This Documentation

- Simics Device Model Developers
  - Read the Registers and FSM pages first (sb_cr and reset_seq_fsm). They define the MMIO API you must implement and the register side-effects.
  - Use capability pages to understand behavioural expectations and to find integration test vectors (e.g., power-good ordering, RCLK handshake, inter-die sync).
  - Implementation notes: model timeouts using reset_sequencer_event and infra_timer; implement read callbacks for resolved fuse/strap registers; ensure outputs are driven atomically when sequencer steps complete.

- Software Feature Validators
  - Use capability pages for behavioral test vectors and expected sequences.
  - Consult the Register Bank Summary for which registers to read/write to trigger or observe behavior (sequencer step, fused/strap readouts).
  - Input/Output tables provide signals to assert/deassert in tests; use events to emulate hardware timing.

- Platform Architects
  - Start with the Device Architecture Diagram and Interface Summary to determine how this HWRS instance connects to other blocks (SCU, NAC, CBB, PUF, RCLK).
  - Use strap/fuse attributes (board_id, socket_id, partition_id) for system provisioning and address-map decisions.
  - Review capability pages to assess how the HWRS impacts platform bring-up, power domains, and constrained timings.

If you need deeper implementation notes, register offset maps, or sequence command table encoding, consult the sb_cr register documentation and the sequencer capability page in the Documentation Index.