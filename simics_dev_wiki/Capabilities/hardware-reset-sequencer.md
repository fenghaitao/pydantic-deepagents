[← Device Overview](overview.md)

---

# hardware-reset-sequencer (dmr_imh_hwrs_fv)

This page documents the Simics DML capability "hardware-reset-sequencer" implemented by the device model dmr_imh_hwrs_fv. The document contains an overview, simulation architecture, working flows, register map, interface signals, validator-oriented behavioral specification and test scenarios, implementation-level notes for device model developers, and platform integration guidance for architects.

Source pointers are inline where available. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml, srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml, srv-pm/code/hwrs-gen2/*.*

---

## Overview

What is modeled
- The HWRS capability models a Hardware Reset Sequencer (HWRS) that drives multiple active-low reset and power-good outputs and responds to multiple platform input signals to sequence cold, warm, and early-boot resets.
- It models a program-like sequencer: a saved step counter (reset_seq_step), a sequence memory interpreted by get_seq_params(), and an event-driven execution engine that drives platform resets and power-good signals in a timed sequence.

Role in device
- Coordinates early-boot and warm/cold reset sequencing for the IMH (Integrated Management Hub) domain and connected NAC subsystems (including SN2SFI and PCIe PERST# lines), and asserts/deasserts SoC and subsystem power-good resets during platform bring-up and reset transitions.

Scope: simulated vs. stubbed
- Simulated: sequencer program counter and saved registers, register read/write side-effects, recurring sequencer event and per-step delays, after-handler short delays, pin-level drive/guard logic (c_pin_out / c_pin_out_nac / c_pin_out_hap templates), input port handlers (pin_state_notifier / s0_pwr_ok_input), breakpoint behavior and completion counters.
- Stubbed / abstracted: no transistor-level or analog power modeling; all timing is modeled as software delays (event posting and after-handlers). Electrical loading, metastability, and real-world timing jitter are not modeled. Some platform-dependent gating (is_primary_imh, is_ioh_with_cnic, CBB strap values) are represented as boolean configuration attributes rather than derived from physical straps.

*Source: reset-sequencer-fsm.dml, hwrs-nac-pins.dml, signal-templates.dml.*

---

## How It's Simulated

Primary DML constructs
- Saved registers: several registers are bank-level saved attributes (for example reset_seq_fsm.reset_seq_step, reset_seq_fsm.reset_seq_wr_seq_done, sb_cr.HWRS_SEQ_CONTROL). These persist across snapshots. *Source: reg-banks-impl.dml; dmr_imh_b0_hwrs_fv_regs.dml*
- Register callbacks: read_action and write_action handlers are used to implement side-effects and read overrides (examples include HWRS_CMD_CURRENT_INDEX get callback, HWRS_DRIVE_PINS_PHASE_3_1 write_action). *Source: dmr_imh_b0_hwrs_fv_regs.dml*
- FSM and events: the sequencer FSM entry function reset_sequencer_fsm() sets FSM status and posts a retriggerable one-shot event reset_sequencer_event; event callback handlers (reset_sequencer_step / reset_sequencer_done) implement per-step behavior and re-posting with per-step delay. *Source: reset-sequencer-fsm.dml*
- After-handlers: short fixed delays use Simics after() one-shot callbacks (for example a 0.001s delay from pre-indication to actual SN2SFI reset). *Source: reset-sequencer-pin-cmds.dml*
- Port and signal templates: inputs use pin_state_notifier, s0_pwr_ok_input, and similar templates that implement signal_raise()/signal_lower() handlers which update saved level and call sequencer helpers; outputs use c_pin_out / c_pin_out_nac / c_pin_out_hap templates that gate drives and maintain a saved level to prevent redundant transitions. *Source: signal-templates.dml, pwrgd-reset-templates.dml, hwrs-nac-pins.dml*

Stubbed aspects
- No electrical analog modeling: pin transitions are boolean signal.raise()/signal.lower() operations.
- Delays in the model are deterministic and implemented by event scheduling (no stochastic timing).

---

## Working Flow

This section describes step-by-step behaviors, registers involved, interface signals, and event scheduling details.

Primary state-machine and flow
- FSM: reset_seq_fsm (internal FSM with status RESET_SEQ_FSM_BUSY). Entry action:
  - reset_sequencer_fsm() sets FSM status to RESET_SEQ_FSM_BUSY, records sequence size and starting index and posts reset_sequencer_event with zero delay so the first step executes immediately. *Source: reset-sequencer-fsm.dml*
- Per-step execution:
  - reset_sequencer_event callback (reset_sequencer_step) reads current step parameters with get_seq_params(reset_seq_step), drives outputs for that step (using drive_pins() and c_pin_out templates), and may advance reset_seq_fsm.reset_seq_step by calling auto_increase.increase_one() (atomic increment).
  - The event handler re-posts itself with the delay read from the next-step parameters. If a breakpoint or completion condition is encountered, the FSM may disarm/cancel the event and update reset_seq_fsm.reset_seq_wr_seq_done. *Source: reset-sequencer-fsm.dml*
- Breakpoint handling:
  - Breakpoints controlled by sb_cr.HWRS_SEQ_CONTROL and sibling HWRS_CMD_BREAK_ON_INDEX register alter sequencer behavior. Reads of HWRS_CMD_CURRENT_INDEX can be overridden by active breakpoints (e.g., return 0xDC, 0x108, or 0x117 depending on breakpoint type). Writing Break_On_Index_Valid from 1→0 removes breakpoint and defers advancement until next sequencer step. *Source: dmr_imh_b0_hwrs_fv_regs.dml*

Examples of flows implemented
- reset-sequencer-progression
  - Trigger: write to sb_cr.HWRS_SEQ_CONTROL or explicit FSM start.
  - Behavior: immediate post of reset_sequencer_event → step handler drives outputs and may auto-increment step → re-post with next-step delay until completion or breakpoint.
  - Result: outputs reflect sequence state; reset_seq_step advanced and reset_seq_wr_seq_done incremented on completion. *Source: reset-sequencer-fsm.dml*
- global-reset-exit -> cold-reset-exit
  - Trigger: GLOBAL_RESET_N.signal_raise() (input handler).
  - Behavior: handler hard-resets registers, drives FDFX PG and CRO clock-valid outputs, and starts/advances the sequencer FSM toward cold-boot targets (S0_PWR_OK). *Source: reset-sequencer-fsm.dml, signal-templates.dml*
- nac-sn2sfi-pre-indication
  - Trigger: c_pin_out_nac.lower() for nac_sn2sfi_rst_pre_ind_n (pre-indication).
  - Behavior: schedules after(0.001s) one-shot which calls nac_sn2sfi_rst_n.lower() to assert the actual reset line; saved c_pin_out_nac.level avoids redundant transitions. *Source: reset-sequencer-pin-cmds.dml, hwrs-nac-pins.dml*

Registers and semantics (high level)
- sb_cr.HWRS_SEQ_CONTROL: write_action mirrors control fields to HWRS_WAIT_PINS_PHASE_3_1, applies Phase-4 disables, drives strap-based die-enable outputs, and affects breakpoint flags and sequencer progression. Reads return stored values. *Source: dmr_imh_b0_hwrs_fv_regs.dml*
- sb_cr.HWRS_CMD_CURRENT_INDEX: read_action may override returned index value if Break_On_Index active (returns special override values depending on type). Writes store normally. *Source: dmr_imh_b0_hwrs_fv_regs.dml*
- sb_cr.HWRS_DRIVE_PINS_PHASE_3_1: write_action checks for Cnic_S0_Pwr_Ok_Int changes and forwards interrupts via cnic_s0_pwr_ok_int_forward(); this field is preserved across hard reset (overrides hard_reset). *Source: dmr_imh_b0_hwrs_fv_regs.dml*
- reset_seq_fsm.reset_seq_step: stored program counter; advanced by auto_increase.increase_one() and by MMIO writes. Reads return live step used by get_seq_params(). *Source: reset-sequencer-fsm.dml*
- reset_seq_fsm.reset_seq_wr_seq_done: completion counter incremented by auto_increase.increase_one() when warm-sequence completion detected. *Source: reset-sequencer-fsm.dml*

Interface signals and conditions (summary)
- Inputs (PORT): S0_PWR_OK, CPUPWRGD, GLOBAL_RESET_N, fdfx_powergood_rst_b, etc. Input templates update saved levels and call sequencer helpers (for example s0_pwr_ok_input.signal_raise() calls reset_sequencer_fsm_pass(RESET_SEQ_TARGET_S0_PWR_OK)). *Source: signal-templates.dml, pwrgd-reset-templates.dml*
- Outputs (CONNECT): soc_pwrgood_rst_b, early_boot_pwrgood_rst_b, nac_sys_rst_n, nac_hif_pcie0_perst_n0, nac_sn2sfi_rst_n, nac_sn2sfi_rst_pre_ind_n, etc. Outputs are driven by c_pin_out / c_pin_out_nac templates with saved level to avoid redundant transitions and guarded by configuration checks (e.g., !is_primary_imh && is_ioh_with_cnic). *Source: hwrs-nac-pins.dml, pwrgd-reset-templates.dml*

Event scheduling
- reset_sequencer_event: retriggerable one-shot posted by reset_sequencer_fsm() with zero delay at entry, re-posted with per-step delay read from sequence parameters. Cancelled by FSM exit or breakpoint logic. *Source: reset-sequencer-fsm.dml*
- nac_sn2sfi_reset_after_pre_ind: one-shot after 0.001s scheduled by pre-indication lower() call; callback asserts nac_sn2sfi_rst_n.lower(). *Source: reset-sequencer-pin-cmds.dml*

---

## Register Map

| Register | Bank | Access Type | Reset Value | Write Side-Effect | Read Side-Effect |
|----------|------|-------------|-------------|-------------------|------------------|
| sb_cr.HWRS_CMD_CURRENT_INDEX | sb_cr | RW | not specified in model | Normal write stores value | get callback may override returned value when a Break-On-Index is active; returns special override (0xDC / 0x108 / 0x117) depending on break type. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |
| sb_cr.HWRS_DRIVE_PINS_PHASE_3_1 | sb_cr | RW | not specified in model | Write to Cnic_S0_Pwr_Ok_Int: if value changes call cnic_s0_pwr_ok_int_forward(new); saved value preserved across hard reset; other fields mirror to HWRS_WAIT_PINS_PHASE_3_1 and stored normally. *Source: dmr_imh_b0_hwrs_fv_regs.dml* | Read: stored-value reads (no special read side-effect). *Source: dmr_imh_b0_hwrs_fv_regs.dml* |
| reset_seq_fsm.reset_seq_step | reset_seq_fsm bank | RW | not specified in model | MMIO writes store value; typical advancement is via auto_increase.increase_one() performed by sequencer logic. *Source: reset-sequencer-fsm.dml* | Read: returns live program counter used by get_seq_params(). *Source: reset-sequencer-fsm.dml* |
| reset_seq_fsm.reset_seq_wr_seq_done | reset_seq_fsm bank | RW | not specified in model | Bus writes update stored counter; sequencer completion increments this via auto_increase.increase_one(). *Source: reset-sequencer-fsm.dml* | Read: stored-value reads (no auto-clear). *Source: reset-sequencer-fsm.dml* |
| sb_cr.HWRS_SEQ_CONTROL | sb_cr | RW | not specified in model | Writes: mirror fields to HWRS_WAIT_PINS_PHASE_3_1, apply Phase-4 IP disables, drive die-enable outputs per CBB strap, may conditionally advance sequencer; writing Break_On_Index_Valid 1→0 removes active breakpoint and defers sequencer advance. *Source: dmr_imh_b0_hwrs_fv_regs.dml* | Read: stored-value reads. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |

(Note: Reset values are implementation-defined in the DML sources and are not included in the capability summary above where not explicitly specified. See reg-banks-impl.dml and device register bank files for reset-value declarations.)

---

## Interface Signals

| Signal | Direction | Interface Type | Trigger Condition | Action |
|--------|-----------|----------------|-------------------|--------|
| S0_PWR_OK | IN (PORT) | signal (s0_pwr_ok_input) | External platform S0 power-ok assertion/deassertion | On raise: set saved level=true and call reset_sequencer_fsm_pass(RESET_SEQ_TARGET_S0_PWR_OK) to advance sequencer toward S0 targets. On lower: update saved level and may disarm timers. *Source: signal-templates.dml* |
| CPUPWRGD | IN (PORT) | signal (pin_state_notifier) | CPU power-good transitions | On raise: clear cpupwrgd_asserted and call reset_sequencer_fsm_pass(RESET_SEQ_TARGET_CPUPWRGOOD). On lower: triggers infrastructure-reset handling and may disarm timers. *Source: signal-templates.dml* |
| GLOBAL_RESET_N | IN (PORT) | signal | Global reset assertion/deassertion | On signal_raise(): updates global_reset_n_asserted, performs hard-reset of registers, raises FDFX PG and CRO clock-valid outputs, and launches/advances reset-sequencer FSM for cold-reset-exit. *Source: reset-sequencer-fsm.dml* |
| fdfx_powergood_rst_b | IN (PORT) | signal (pin_state_notifier) | FDFX rail power-good transitions | On raise/lower updates saved level and calls notify_level_change/on_change which feed into HWRS logic to release related resets. *Source: pwrgd-reset-templates.dml* |
| early_boot_pwrgood_rst_b | OUT (CONNECT) | signal (c_pin_out) | Driven by sequencer step and power-good logic | Active-low early-boot power-good reset: lowered during non-power-good early-boot conditions, raised when power-good confirmed. *Source: pwrgd-reset-templates.dml* |
| soc_pwrgood_rst_b | OUT (CONNECT) | signal (c_pin_out) | Driven by sequencer/power-good logic | Active-low SoC power-good reset asserted when SoC rails invalid; deasserted on power-good confirmation. *Source: pwrgd-reset-templates.dml* |
| nac_sys_rst_n | OUT (CONNECT) | signal (c_pin_out_nac) | Driven by sequencer steps for NAC resets | Active-low NAC system reset driven during deep-warm-reset entry and NAC side-reset phases; guarded by is_ioh_with_cnic && !is_primary_imh. *Source: hwrs-nac-pins.dml* |
| nac_sn2sfi_rst_pre_ind_n | OUT (CONNECT) | signal (c_pin_out_nac) | Pre-indication driven by sequencer step | On lower: schedules a 1 ms after-handler that later asserts nac_sn2sfi_rst_n. Saved level prevents redundant pre-indications. *Source: reset-sequencer-pin-cmds.dml* |
| nac_sn2sfi_rst_n | OUT (CONNECT) | signal (c_pin_out_nac) | One-shot after pre-indication or direct sequencer step | Active-low SN2SFI reset asserted either immediately if commanded or via 1 ms delayed scheduled by pre-indication. *Source: reset-sequencer-pin-cmds.dml* |
| nac_hif_pcie0_perst_n0 | OUT (CONNECT) | signal (c_pin_out_nac) | Driven by sequencer NAC side-reset steps | Active-low PCIe PERST# for NAC HIF PCIe port 0, asserted during NAC side-reset phases. *Source: hwrs-nac-pins.dml* |

(Only the primary signals mentioned in analysis are listed. See hwrs-nac-pins.dml and pwrgd-reset-templates.dml for the full set of CONNECT nodes.)

---

## Behavioral Specification (for Software Feature Validators)

Each statement below is written as a WHEN → THEN assertion suitable for test automation.

1. WHEN software writes sb_cr.HWRS_SEQ_CONTROL to start a sequencer step (or writes an enabling field) → THEN the HWRS model posts reset_sequencer_event immediately and at least one sequencer-step action (output drive) is observable on the first event callback (e.g., an active-low reset on a CONNECT pin asserted). Verification: observe reset_seq_fsm status = RESET_SEQ_FSM_BUSY and output pin transition within simulation time << configured step delay. *Source: reset-sequencer-fsm.dml*

2. WHEN sb_cr.HWRS_CMD_CURRENT_INDEX is read while Break-On-Index is active → THEN the read returns the breakpoint-specific override value rather than the stored value (possible override values include 0xDC, 0x108, 0x117 depending on breakpoint type). Verification: set corresponding HWRS_CMD_BREAK_ON_INDEX and read HWRS_CMD_CURRENT_INDEX; compare returned value. *Source: dmr_imh_b0_hwrs_fv_regs.dml*

3. WHEN sb_cr.HWRS_DRIVE_PINS_PHASE_3_1.Cnic_S0_Pwr_Ok_Int is written with a value different from current saved value → THEN cnic_s0_pwr_ok_int_forward(new) is invoked, and the saved field value is updated and preserved across a hard reset. Verification: write bit 1 then 0 and check that cnic interrupt forwarding callbacks occur and the value remains after a simulated GLOBAL_RESET_N-triggered hard-reset path. *Source: dmr_imh_b0_hwrs_fv_regs.dml*

4. WHEN nac_sn2sfi_rst_pre_ind_n is lowered by a sequencer step (pre-indication) → THEN an after-handler is scheduled for 0.001s later which asserts nac_sn2sfi_rst_n (actual reset). Verification: observe pre-indication transition, schedule existence, and then the nac_sn2sfi_rst_n assertion exactly ~1 ms later in simulation time. *Source: reset-sequencer-pin-cmds.dml*

5. WHEN S0_PWR_OK is asserted (signal_raise()) on the primary IMH input → THEN the s0_pwr_ok_input handler calls reset_sequencer_fsm_pass(RESET_SEQ_TARGET_S0_PWR_OK) and the sequencer advances to the configured S0 target step. Verification: assert S0_PWR_OK, confirm saved level true and that reset_seq_fsm advances to a step that drives S0-related outputs (and possibly sets trigger_cold_rst_exit_done). *Source: signal-templates.dml*

6. WHEN a sequencer reaches warm-sequence completion → THEN reset_seq_fsm.reset_seq_wr_seq_done is incremented via auto_increase.increase_one(). Verification: monitor reset_seq_wr_seq_done before and after completion to observe +1 increment. *Source: reset-sequencer-fsm.dml*

---

## Test Case Scenarios (for Software Feature Validators)

| Scenario | Setup | Action | Expected Result | Verification Point |
|----------|-------|--------|-----------------|--------------------|
| Start sequencer and observe first step output | Ensure device in default state; configure HWRS sequence memory so first step drives soc_pwrgood_rst_b low | Write sb_cr.HWRS_SEQ_CONTROL to enable/start sequence (or call reset_sequencer_fsm()) | reset_sequencer_event posted immediately; soc_pwrgood_rst_b driven low within event callback | Observe reset_seq_fsm status == BUSY and soc_pwrgood_rst_b.signal_lower() within simulation time 0..few ms |
| Break-on-index read override test | Program HWRS_CMD_BREAK_ON_INDEX with COLD break index active and set HWRS_CMD_CURRENT_INDEX stored value to 0x00 | Read sb_cr.HWRS_CMD_CURRENT_INDEX | Read returns 0xDC (COLD-break override) instead of stored 0x00 | MMIO read value equals expected override (0xDC) |
| CNIC S0 power-ok interrupt forward and hard-reset persistence | Write HWRS_DRIVE_PINS_PHASE_3_1.Cnic_S0_Pwr_Ok_Int = 1 then = 0; then trigger GLOBAL_RESET_N.signal_raise() hard-reset path | cnic_s0_pwr_ok_int_forward invoked on changes; saved field value is preserved across hard reset if write indicates preservation | Inspect model logs/callbacks for forward calls; read back HWRS_DRIVE_PINS_PHASE_3_1.Cnic_S0_Pwr_Ok_Int after hard-reset and expect preserved value |
| NAC SN2SFI pre-indication -> reset timing | Configure sequencer step to lower nac_sn2sfi_rst_pre_ind_n | Execute sequencer to run that step | nac_sn2sfi_rst_pre_ind_n goes low, then after ~0.001s nac_sn2sfi_rst_n goes low | Inspect timeline of output signal transitions: pre-indication low at t0, actual reset low at t0+0.001s |
| S0 power-ok advances sequencer to S0 target | Ensure sequencer is waiting on S0 target; S0_PWR_OK input currently low | Assert S0_PWR_OK (signal_raise) on PORT | s0_pwr_ok_input handler calls reset_sequencer_fsm_pass and sequencer advances; appropriate outputs (S0-related) are driven | Check reset_seq_step advanced to S0-target step and outputs changed accordingly |

Notes for test automation
- Use Simics event/time control to observe scheduled after-handlers (sim-time granularity).
- Use saved-register reads and MMIO reads to observe internal counters (reset_seq_step, reset_seq_wr_seq_done).
- Validate gating logic by toggling platform configuration attributes (is_primary_imh, is_ioh_with_cnic) and ensuring NAC outputs are suppressed when appropriate.

---

## Implementation Notes (for Simics Device Model Developers)

Key DML source files (primary)
- srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml — FSM implementation, event posting, step handler, and sequencer helpers. *Source: reset-sequencer-fsm.dml*
- srv-pm/code/hwrs-gen2/reset-sequencer-pin-cmds.dml — pin-command sequences, pre-indication and after-handler implementations. *Source: reset-sequencer-pin-cmds.dml*
- srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml — power-good output templates and drive_pins helpers. *Source: pwrgd-reset-templates.dml*
- srv-pm/code/hwrs-gen2/hwrs-nac-pins.dml — NAC pin templates and guards (is_primary_imh / is_ioh_with_cnic checks). *Source: hwrs-nac-pins.dml*
- srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml — register declarations and read/write callbacks. *Source: dmr_imh_b0_hwrs_fv_regs.dml*
- srv-pm/code/hwrs-gen2/attributes.dml, hwrs-straps.dml, hwrs-ip-disable.dml — configuration attributes / strap-based behavior. *Source: attributes.dml, hwrs-straps.dml, hwrs-ip-disable.dml*
- common/code/platform-common/unified-common-code/signals/signal-templates.dml — pin_state_notifier / s0_pwr_ok_input templates. *Source: signal-templates.dml*

Template dependencies and inheritance chain
- Input templates: s0_pwr_ok_input and pin_state_notifier derive common behavior for saved level, notify_level_change, and on_change handlers. Implementations invoke sequencer helpers. *Source: signal-templates.dml*
- Output templates: c_pin_out, c_pin_out_nac, c_pin_out_hap provide saved-level tracking, guard conditions and connect to remote port.signal_raise()/signal_lower(). The HWRS device composes these for each reset/power-output. *Source: hwrs-nac-pins.dml, pwrgd-reset-templates.dml*
- Sequencer uses auto_increase template (or helper) for atomic increments of saved counters (reset_seq_step and reset_seq_wr_seq_done). *Source: reset-sequencer-fsm.dml*

Extension / override points
- Register read_action/write_action callbacks (dmr_imh_b0_hwrs_fv_regs.dml) — add or modify side-effects; e.g., implement additional mirroring or breakpoint semantics.
- Sequence parameter mapping (get_seq_params()) — extend to support new sequence command types or timing fields.
- Step handler (reset_sequencer_step) — override to add logging, additional pin actions, or to introduce simulated condition checks.
- Output templates — extend c_pin_out_nac guard conditions or add additional saved-state logic to emulate hardware faults.
- After-handlers — can be replaced or parameterized to model different pre-indication durations.

Simulation fidelity notes / known differences
- Timing and delays are deterministic and software-specified; they do not model analog/electrical behavior or variability.
- The saved-level avoidance of redundant transitions is a behavioral optimization and may suppress simulated toggles that real hardware could see transiently.
- Breakpoint read overrides return fixed magic values to emulate legacy behavior (0xDC, 0x108, 0x117) rather than dynamic hardware trap codes.
- Some platform gating (is_primary_imh, is_ioh_with_cnic, CBB straps) are represented as boolean attributes rather than derived from physical strap pins.

Debugging and observability recommendations
- Instrument reset_sequencer_step and event posting with debug logs to trace per-step parameter reads and scheduled next delays.
- Expose saved attributes (reset_seq_step, reset_seq_wr_seq_done, breakpoint flags) as visible MMIO or Simics attributes for test harness queries.
- Use saved-levels on c_pin_out templates to assert if duplicate drives are being suppressed.

---

## Platform Integration Notes (for Platform Architects)

Role in platform
- The HWRS capability is the central reset sequencing controller for early-boot and warm/cold reset flows on the IMH/BMC domain, coordinating power-good assertions and subsystem reset release (SoC, NAC, PCIe PERST#) and interfacing with platform power-management signals to sequence bring-up.

Required signal connections
- Inputs the platform must provide:
  - S0_PWR_OK (platform S0 power state) — required for cold-boot exit sequencing. *Source: signal-templates.dml*
  - CPUPWRGD (CPU power-good) — used in reset sequencing and potentially to trigger infrastructure reset logic. *Source: signal-templates.dml*
  - GLOBAL_RESET_N — global reset source, drives hard-reset path and sequencer restart. *Source: reset-sequencer-fsm.dml*
  - fdfx_powergood_rst_b — FDFX rail PG used to drive early-boot PG outputs. *Source: pwrgd-reset-templates.dml*
- Outputs the HWRS drives (examples — full list in device DML):
  - soc_pwrgood_rst_b — SoC power-good reset (active-low).
  - early_boot_pwrgood_rst_b — early-boot power-good reset.
  - nac_sys_rst_n, nac_hif_pcie0_perst_n0, nac_sn2sfi_rst_n, nac_sn2sfi_rst_pre_ind_n — NAC subsystem resets and pre-indication signals.
  - CNIC-related S0_PWR_OK interrupt forwarded via cnic_s0_pwr_ok_int forwarding. *Source: hwrs-nac-pins.dml, pwrgd-reset-templates.dml*

Dependencies on other capabilities/services
- CBB strap state and IMH role attributes (is_primary_imh, is_ioh_with_cnic) influence whether NAC outputs are driven. These are configured via hwrs-straps.dml / attributes.dml. *Source: hwrs-straps.dml, attributes.dml*
- Sequence memory / parameters (get_seq_params()) may be shared with other HWRS code modules; platform integrators must ensure sequence tables are present or properly configured in device DML.
- The model depends on platform services that generate S0_PWR_OK, CPUPWRGD, and GLOBAL_RESET_N signals to drive sequencing.

Configuration parameters that affect behavior
- is_primary_imh (boolean) — suppresses NAC-targeted outputs on primary IMH.
- is_ioh_with_cnic (boolean) — enables NAC/CNIC output driving.
- Strap and CBB-related attributes (die-enable, Phase-4 disables) — affect whether certain outputs are driven or programming is allowed. *Source: hwrs-straps.dml, hwrs-ip-disable.dml*
- Sequence memory contents and sequence size/start index — determine which sequence steps execute and corresponding delays.

Integration recommendations
- Connect HWRS inputs to the platform power-management model so that S0_PWR_OK and CPUPWRGD transitions mirror the platform bring-up sequence.
- Ensure that the host of NAC and PCIe reset consumers are connected to the corresponding CONNECT nodes so their reset inputs receive the active-low signals from HWRS.
- For validation, provide hooks to assert or inject breakpoints via HWRS_CMD_BREAK_ON_INDEX to test breakpoint behavior and read overrides.

---

If you need, I can:
- produce specific Simics scenarios (Simscript or test harness steps) to exercise each WHEN→THEN case,
- extract a full list of all CONNECT/PORT nodes from the DML for wiring diagrams,
- or provide a minimal DML patch template showing how to add a new sequencer command type.