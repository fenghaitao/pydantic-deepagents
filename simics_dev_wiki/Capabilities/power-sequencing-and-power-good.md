[← Device Overview](overview.md)

---

# power-sequencing-and-power-good — dmr_imh_hwrs_fv

This page documents the Simics DML capability "power-sequencing-and-power-good" implemented by the dmr_imh_hwrs_fv device model. It covers what is modeled, how the model behaves, testable behavioral specifications, concrete test scenarios, implementation notes for model developers, and platform integration guidance for architects.

Source references in this document point to the DML artifacts and code maps that implement the capability. Where a specific file is relevant it is cited as *Source: filename*.

---

## Overview

This capability models a substantial portion of the HWRS (hardware reset sequencing) domain for power sequencing and power-good interactions inside the dmr_imh_hwrs_fv device. It implements:

- power-good input handling (AUX_PWRGOOD, CPUPWRGD),
- platform reset handling (PLTRSTB active-low),
- a multi-phase warm-reset unwinding sequence (PM-unwind → preamble → die-to-die-reset preparation → DIDT staggering),
- a reset sequencer finite state machine (reset_sequencer_fsm) driven by inputs and register writes,
- numerous output signals that represent power-good and reset outputs to other platform components (punit_pm_unwind, hwrs_set_warm_reset_preamble_run, yyDIE_ENABLEx, vinf_pwrgood_rst_b, etc.),
- register side-effect logic that mirrors configuration into outputs and advances the FSM (notably sb_cr.HWRS_SEQ_CONTROL and sb_cr.HWRS_DRIVE_PINS_PHASE_3_1).

Scope — simulated vs. stubbed:
- Simulated: multi-phase infra_timer-driven warm-reset flow, sequencer FSM transitions and guards, saved attributes and straps, port callbacks for input signals, output drives via c_pin_out/c_pin_out_hap, register after-write behaviors that drive outputs and invoke FSM progression.
- Partially simulated / modeled at logical level: fuse/strapped behavior used to resolve yyDIE_ENABLEx and resolved IP-disable read paths (returned as cr_reg.val | fuses_reg.val); precise electrical timing and analog dI/dt are represented by logical timers and sequenced toggles rather than analog waveforms.
- Stubbed / not modeled: any analog or micro-architectural details outside HWRS outputs (e.g., silicon-internal delays beyond configured timeouts), and read-side effects beyond those described.

*Source: srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml, srv-pm/code/hwrs-gen2/hwrs-timer.dml, srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*

---

## How It's Simulated

Implementation primitives and design patterns used:

- Saved attributes (uint64_attr, strap_attr_u64, boolean saved attributes) to persist configuration and state across checkpoints and (selectively) resets.
  - Examples: unwind_timeout_us, preamble_timeout_us, didt_timeout_us, cpupwrgd_asserted, aux_pwr_retained_register. *Source: srv-pm/code/hwrs-gen2/attributes.dml*
- Port callbacks implemented through pin_state_notifier templates for input signals. Input methods implement signal_raise and signal_lower to update saved state and trigger sequencer actions.
  - Examples: CPUPWRGD.signal_raise/low, AUX_PWRGOOD handlers, PLTRSTB on_change. *Source: capability analysis / port descriptions*
- Outputs implemented using c_pin_out and c_pin_out_hap templates to drive remote ports and publish HAP notifications for observers.
  - Examples: punit_pm_unwind, hwrs_set_warm_reset_preamble_run, cnic S0 interrupt via c_pin_out_hap. *Source: pwrgd-reset-templates.dml*
- Registers implemented using register templates with after_write callbacks and field-specific write actions. Key registers:
  - sb_cr.HWRS_SEQ_CONTROL — after_write implements Imh_Disable_Programming_Done handling, HWRS_WAIT_PINS_PHASE_3_1 mirroring, phase-4 IP disables, and optional sequencer-stepping when Break_On_Index_Valid toggles. *Source: sb_cr.HWRS_SEQ_CONTROL.after_write*
  - sb_cr.HWRS_DRIVE_PINS_PHASE_3_1 — field Cnic_S0_Pwr_Ok_Int implements write_action that toggles cnic S0 interrupt via c_pin_out HAP and is sticky across hard_reset. *Source: sb_cr.HWRS_DRIVE_PINS_PHASE_3_1 write description*
  - sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3 / DWORD7 — RO registers returning cr_reg.val | fuses_reg.val. *Source: ip_disable_resolved_cr_dword3.read, ip_disable_resolved_cr_dword7.get*
- A retriggerable infra_timer event object implements a four-phase timeout chain. The timer is armed during warm-reset unwind entry and each phase after-handler drives outputs and posts the next phase using microsecond-scale delay attributes (unwind_timeout_us, preamble_timeout_us, didt_timeout_us). The timer can be canceled on PLTRST assertion. *Source: hwrs-timer.dml; infra_timer.after description*
- reset_sequencer_fsm implemented as a DML FSM driver with a driver function reset_seq_fsm_driver and helper reset_sequencer_fsm_pass to advance toward named targets. It is driven by inputs, register writes and timer events. *Source: reset-sequencer-fsm.dml*

What is intentionally not modeled in detail:
- Electrical analog behavior of rail ramps or current transients (abstracted as timer-driven phases).
- Some peripheral-specific handshake timing when those peripherals are not connected (the model will drive c_pin_out but the remote side behavior may be absent).

*Source: srv-pm/code/hwrs-gen2/*

---

## Working Flow

This section describes the behavior, FSM interactions, registers involved, signals, and timed events.

Primary flows:

1) FLOW: pm-unwind-warm-reset-entry
- Trigger: PLTRST de-assert (PLTRSTB transitions from asserted->deasserted; implemented in pltrstb_input.on_change with raise==false).
  - pltrstb_input.on_change calls do_pm_unwind(), records warm-reset entry state, clears side-reset flags, arms infra_timer phase-1. *Source: pltrstb_input.on_change; do_pm_unwind description*
- do_pm_unwind():
  - Drives punit_pm_unwind output asserted via c_pin_out drive. *Source: pwrgd-reset-handlers.dml*
  - Posts infra_timer phase-1 using unwind_timeout_us microseconds. *Source: hwrs-timer.dml; unwind_timeout_us attr*
- infra_timer expiry handlers:
  - Phase 1 expiry: assert hwrs_set_warm_reset_preamble_run and post next phase after preamble_timeout_us.
  - Phase 2 expiry: prepare die-to-die resets; configure isolation/side-reset outputs.
  - Phase 3/4 expiry(s): run DIDT (dI/dt) stagger using didt_timeout_us; toggle yyDIE_ENABLEx/isolation pins in sequence.
  - Completion: clear punit_pm_unwind and any temporary phase-run signals; remote ports observe sequence of CONNECT drives. *Source: infra_timer phase handlers*

Observable results:
- punit_pm_unwind asserted during unwind, hwrs_set_warm_reset_preamble_run asserted during preamble, side reset/isolation and yyDIE_ENABLEx toggles posted to remote ports in sequence. *Source: FLOW description*

2) FLOW: cpu-pwrgood-driven-sequencer-advance
- Trigger: CPUPWRGD.signal_raise.
  - CPUPWRGD.signal_raise sets cpupwrgd_asserted saved attribute to true and calls reset_sequencer_fsm_pass(RESET_SEQ_TARGET_CPUPWRGOOD). *Source: CPUPWRGD.signal_raise*
- reset_sequencer_fsm_pass / reset_seq_fsm_driver:
  - Evaluates current sequencer state, strap/config attributes (e.g., fxr_disable_strap) and may skip steps accordingly.
  - When advancing, drivers assert/release outputs (vinf_pwrgood_rst_b released, xxREFCLK_Rdy asserted) and may drive IMH/CBB/SCU handshake pins depending on configuration.
- Sequencer may be constrained by HWRS_SEQ_CONTROL Break_On_Index_Valid or HWRS_WAIT_PINS_PHASE_3_1 bits (writes can enable/disable breakpoints and mirror fields). *Source: sb_cr.HWRS_SEQ_CONTROL.after_write*

Register involvement and semantics (selected):
- sb_cr.HWRS_SEQ_CONTROL (RW): writing Imh_Disable_Programming_Done drives yyDIE_ENABLEx per fuse, mirrors to HWRS_WAIT_PINS_PHASE_3_1, applies IP-disable masks and may advance sequencer if break_on_index_valid is not active. Break_On_Index_Valid write from 1->0 removes a breakpoint and can allow sequencer progression. Writes also assert xxREFCLK_Rdy depending on fields. Reads have no special effect in the model. *Source: sb_cr.HWRS_SEQ_CONTROL.after_write*
- sb_cr.HWRS_DRIVE_PINS_PHASE_3_1 (RW): fields like Cnic_S0_Pwr_Ok_Int implement write_action to raise/lower CNIC S0 power-OK interrupt via HAP-driven c_pin_out; field values are sticky across hard_reset. Reads return stored values. *Source: HWRS_DRIVE_PINS_PHASE_3_1 write description*
- sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3 / DWORD7 (RO): reads return cr_reg.val | fuses_reg.val (resolved IP-disable). Writes are ignored. *Source: ip_disable_resolved_cr_dword3.read, ip_disable_resolved_cr_dword7.get*
- aux_pwr_retained_register (RW): saved attribute; writes update stored state that persists across auxiliary power transitions. No immediate side-effect. *Source: aux_pwr_retained_register.write*
- cpupwrgd_asserted register/state (RW in DML map): holds current CPUPWRGD input state (updated by port callbacks). Reads reflect current saved state. *Source: cpupwrgd_asserted description*

Interface participation:
- Inputs: AUX_PWRGOOD, CPUPWRGD, PLTRST (implemented as pin_state_notifier / aux_pwrgd_input / CPUPWRGOOD_input / pltrstb_input templates). Their signal_raise/low handlers update saved state and trigger FSM steps, arm/disarm timers, or manipulate retention logic. *Source: port descriptions*
- Outputs (CONNECTs): punit_pm_unwind, hwrs_set_warm_reset_preamble_run, scu_start_pmsync_handshake, scu_config_req, yyDIE_ENABLEx, vinf_pwrgood_rst_b, xxREFCLK_Rdy, imh2cbb_hwsync_ack_out, cnic_s0_pwr_ok_int (via HAP). Outputs are driven using c_pin_out and c_pin_out_hap templates during sequencer steps, infra_timer phases, or register write handlers. *Source: Interface Output descriptions*

Event scheduling:
- infra_timer is retriggerable and implements multi-phase timeouts; delay values are microsecond-scale and configurable via attributes unwind_timeout_us, preamble_timeout_us, didt_timeout_us. PLTRST assertion cancels the timer; phase handlers post subsequent phases. *Source: hwrs-timer.dml, attributes.dml*

---

## Register Map

| Register | Bank | Access Type | Reset Value | Write Side-Effect | Read Side-Effect |
|----------|------|-------------|-------------|-------------------|------------------|
| sb_cr.HWRS_SEQ_CONTROL | sb_cr | RW | implementation-defined / device default | Imh_Disable_Programming_Done: drives yyDIE_ENABLEx per fuse, mirrors to HWRS_WAIT_PINS_PHASE_3_1; applies phase-4 IP disables; if Break_On_Index_Valid transitions 1→0 then remove sequencer breakpoint and may advance sequencer; writes can assert xxREFCLK_Rdy and progress FSM. *Source: sb_cr.HWRS_SEQ_CONTROL.after_write* | No special read side-effect modeled |
| sb_cr.HWRS_DRIVE_PINS_PHASE_3_1 | sb_cr | RW | implementation-defined | Field Cnic_S0_Pwr_Ok_Int: on change invokes cnic_s0_pwr_ok_int_forward(); writing 1 raises CNIC S0 interrupt via c_pin_out HAP; value is sticky across hard_reset. *Source: sb_cr.HWRS_DRIVE_PINS_PHASE_3_1 write* | Reads return stored field values |
| sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3 | sb_cr | RO | cr_reg.val | Writes ignored / rejected; read returns cr_reg.val | Returns cr_reg.val | fuses_reg.val ORed: read returns cr_reg.val | fuses_reg.val (resolved bits). *Source: ip_disable_resolved_cr_dword3.read* |
| sb_cr.IP_DISABLE_RESOLVED_CR_DWORD7 | sb_cr | RO | cr_reg.val | Writes ignored | Read returns cr_reg.val | fuses_reg.val (64-bit resolved arbitration). *Source: ip_disable_resolved_cr_dword7.get* |
| aux_pwr_retained_register | misc / retained | RW | false / implementation-defined | Stores aux_pwr_retained saved attribute; no immediate Simics-side effect; preserved across aux-power transitions. *Source: aux_pwr_retained_register.write* | Read returns stored value |
| cpupwrgd_asserted (register/view) | misc / state | RW (updated by port) | false | Set/cleared by CPUPWRGD.port callbacks (signal_raise / signal_lower). Used by sequencer guards. *Source: CPUPWRGD.signal_raise* | Read-only view of saved assert state |

Notes:
- Reset values are not uniformly documented in the DML excerpts; tests should not assume specific reset defaults unless provided by platform configuration. *Source: code map and register snippets*

---

## Interface Signals

| Signal | Direction | Interface Type | Trigger Condition | Action |
|--------|-----------|----------------|-------------------|--------|
| AUX_PWRGOOD | PORT (IN) | signal / pin_state_notifier | External auxiliary power-good assert/deassert | Updates saved aux power-good level; falling edge triggers VNN power-domain handling and sequencing guards. *Source: AUX_PWRGOOD description* |
| CPUPWRGD | PORT (IN) | signal / pin_state_notifier | CPU rails assert/deassert power-good | signal_raise sets cpupwrgd_asserted=true and calls reset_sequencer_fsm_pass(RESET_SEQ_TARGET_CPUPWRGOOD); signal_lower clears state and may disarm infra timers. *Source: CPUPWRGD description* |
| PLTRSTB (PLTRST) | PORT (IN) | signal / pin_state_notifier (active-low) | PLTRST asserted / deasserted | On deassert (PLTRST release) handler calls do_pm_unwind() and arms infra_timer; on assert clears warm-reset flags, cancels timers and lowers outputs. *Source: PLTRST description* |
| punit_pm_unwind | CONNECT (OUT) | c_pin_out | do_pm_unwind() invoked on PLTRST deassert | Driven ASSERT during PM-unwind phase; deasserted on unwind completion or PLTRST assert. *Source: punit_pm_unwind description* |
| hwrs_set_warm_reset_preamble_run | CONNECT (OUT) | c_pin_out | infra_timer phase 2 (preamble) | Asserted during preamble; cleared after phase completes or on PLTRST assert. *Source: infra_timer.phase2.after* |
| yyDIE_ENABLEx | CONNECT (OUT) | c_pin_out | sb_cr.HWRS_SEQ_CONTROL.Imh_Disable_Programming_Done write and infra_timer sequencing | Driven per IMH disable programming and fuse state; toggled during DIDT/unwind phases. *Source: HWRS_SEQ_CONTROL.after_write* |
| vinf_pwrgood_rst_b | CONNECT (OUT) | c_pin_out | sequencer advancement toward CPUPWRGOOD | Released (deasserted low-active) as sequencer advances after CPUPWRGD and other guards. *Source: FLOW cpu-pwrgood description* |
| xxREFCLK_Rdy | CONNECT (OUT) | c_pin_out | sb_cr.HWRS_SEQ_CONTROL writes / sequencer | May be asserted by writes to HWRS_SEQ_CONTROL; used as BCLK-ready indicator. *Source: HWRS_SEQ_CONTROL.after_write* |
| scu_start_pmsync_handshake / scu_config_req | CONNECT (OUT) | c_pin_out | sequencer or infra_timer handlers | Asserted when HWRS requires SCU coordination; deasserted after handshake completion. *Source: Interface Output descriptions* |
| imh2cbb_hwsync_ack_out | CONNECT (OUT) | c_pin_out | sequencer progress / IMH handshake | Toggled depending on configuration and sequencer state. *Source: cpu-pwrgood flow and outputs* |
| cnic_s0_pwr_ok_int | CONNECT (OUT) | c_pin_out_hap | Write to sb_cr.HWRS_DRIVE_PINS_PHASE_3_1.Cnic_S0_Pwr_Ok_Int | HAP-driven signal: writing 1 raises interrupt; writing 0 lowers it; changes generate HAP notifications to observers. Sticky across hard_reset. *Source: HWRS_DRIVE_PINS_PHASE_3_1.write*

Notes:
- All outputs are driven via c_pin_out templates; remote connections will observe the level changes via HAP callbacks if connected. *Source: pwrgd-reset-templates.dml*

---

## Behavioral Specification (for Software Feature Validators)

Each statement is formatted as: WHEN -> THEN. Observable results are those accessible inside Simics (register reads, HAP notifications on c_pin_out, port-level callbacks, saved attribute reads).

1) WHEN PLTRST is deasserted (active-low PLTRSTB rises) -> THEN the model calls do_pm_unwind(), asserts punit_pm_unwind, and arms the infra_timer to begin phase-1 using unwind_timeout_us. Verification: HAP on punit_pm_unwind shows ASSERT and infra_timer scheduled event exists. *Source: pltrstb_input.on_change; do_pm_unwind; infra_timer.post*

2) WHEN infra_timer phase-2 expires (preamble_timeout_us elapsed) during PM-unwind -> THEN hwrs_set_warm_reset_preamble_run is driven ASSERT and a subsequent infra_timer phase is posted. Verification: HAP notifications show hwrs_set_warm_reset_preamble_run ASSERT, next infra_timer event scheduled. *Source: infra_timer.phase2.after*

3) WHEN CPUPWRGD.signal_raise occurs -> THEN the cpupwrgd_asserted saved attribute becomes true and reset_sequencer_fsm_pass(RESET_SEQ_TARGET_CPUPWRGOOD) is invoked; as the FSM advances, vinf_pwrgood_rst_b is released and xxREFCLK_Rdy may assert consistent with HWRS_SEQ_CONTROL configuration. Verification: cpupwrgd_asserted register reads true; HAPs show vinf_pwrgood_rst_b change and xxREFCLK_Rdy asserted if configured. *Source: CPUPWRGD.signal_raise; cpu-pwrgood flow*

4) WHEN software writes sb_cr.HWRS_SEQ_CONTROL.Imh_Disable_Programming_Done from 0->1 -> THEN yyDIE_ENABLEx outputs are driven according to fuse state, HWRS_WAIT_PINS_PHASE_3_1 is updated to match Imh_Disable_Programming_Done, and phase-4 IP-disable masks are applied; if Break_On_Index_Valid is not set the sequencer may advance. Verification: readback of HWRS_WAIT_PINS_PHASE_3_1 reflects the written value; HAPs on yyDIE_ENABLEx show the driven levels; FSM state advances when break is cleared. *Source: HWRS_SEQ_CONTROL.after_write*

5) WHEN software writes sb_cr.HWRS_DRIVE_PINS_PHASE_3_1.Cnic_S0_Pwr_Ok_Int toggling the bit -> THEN a c_pin_out_hap-driven CNIC S0 Power-OK interrupt is raised (on write=1) or lowered (on write=0) and the bit value persists across hard_reset. Verification: HAP notification observed; readback of the register shows the set value after a model hard_reset operation. *Source: HWRS_DRIVE_PINS_PHASE_3_1 write*

6) WHEN PLTRST is asserted during an in-flight infra_timer sequence -> THEN infra_timer is canceled, punit_pm_unwind and temporary preamble outputs are deasserted, and warm-reset side state is cleared. Verification: scheduled infra_timer events are gone, HAPs show outputs deasserted, HWRS_STATUS shows warm-reset recorded. *Source: infra_timer cancel behavior; PLTRST assertion handling*

7) WHEN software reads sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3 or DWORD7 -> THEN the read returns the bitwise OR of cr_reg.val and fuses_reg.val (resolved state) and writes to these registers are ignored. Verification: write attempts get rejected or ignored; read returns ORed value consistent with simulated fuses. *Source: ip_disable_resolved_cr_dword3.read, ip_disable_resolved_cr_dword7.get*

---

## Test Case Scenarios (for Software Feature Validators)

Provide concrete scenarios with environment setup, actions, expected results and verification points.

Scenario 1: PM Unwind Warm-Reset Entry
- Setup: Connect a test observer to punit_pm_unwind and hwrs_set_warm_reset_preamble_run HAPs; ensure infra_timer timeouts are set to a short value (unwind_timeout_us=100, preamble_timeout_us=100, didt_timeout_us=50) for fast tests. *Source: attributes.dml*
- Action: Drive PLTRSTB from asserted to deasserted (simulate PLTRST deassert).
- Expected Result: punit_pm_unwind HAP shows ASSERT immediately; infra_timer scheduled; after ~100us hwrs_set_warm_reset_preamble_run HAP shows ASSERT; subsequent DIDT sequence toggles yyDIE_ENABLEx observable via HAPs.
- Verification Point: Check saved attribute warm-reset entry recorded; confirm HAP notifications sequence punit_pm_unwind -> hwrs_set_warm_reset_preamble_run -> yyDIE_ENABLEx toggles.

Scenario 2: CPUPWRGD-driven Sequencer Advance
- Setup: Ensure sb_cr.HWRS_SEQ_CONTROL has Break_On_Index_Valid cleared or set as appropriate; connect observers to vinf_pwrgood_rst_b and xxREFCLK_Rdy.
- Action: Assert CPUPWRGD (signal_raise).
- Expected Result: cpupwrgd_asserted reads true; reset_sequencer_fsm advances to CPUPWRGOOD target; vinf_pwrgood_rst_b is released and xxREFCLK_Rdy asserted (if HWRS_SEQ_CONTROL configuration allows).
- Verification Point: Read cpupwrgd_asserted, read sequencer state (if exposed), HAPs show vinf_pwrgood_rst_b and xxREFCLK_Rdy level changes.

Scenario 3: Register-Driven CNIC S0 Interrupt Sticky Behavior
- Setup: Attach HAP observer to cnic_s0_pwr_ok_int; set up to capture HAP events; optionally perform a Simics hard_reset call.
- Action: Write sb_cr.HWRS_DRIVE_PINS_PHASE_3_1.Cnic_S0_Pwr_Ok_Int = 1; then perform hard_reset(); then read field.
- Expected Result: HAP observer records interrupt ASSERT on write; after hard_reset read returns 1 (sticky behavior).
- Verification Point: HAP captured rising event; readback after hard_reset returns unchanged value. *Source: HWRS_DRIVE_PINS_PHASE_3_1 write*

Scenario 4: HWRS_SEQ_CONTROL Break Removal Advances Sequencer
- Setup: Set Break_On_Index_Valid bit = 1 to block sequencer progression at an index; attach observer to sequencer progression outputs (e.g., imh2cbb_hwsync_ack_out).
- Action: Write Break_On_Index_Valid from 1->0 in sb_cr.HWRS_SEQ_CONTROL.
- Expected Result: The model removes the breakpoint and deferred sequencer may advance; HAP outputs or FSM state reflect advancement.
- Verification Point: Confirm HWRS_WAIT_PINS_PHASE_3_1 mirroring behavior and downstream outputs toggle as sequencer continues. *Source: HWRS_SEQ_CONTROL.after_write*

Scenario 5: IP Disable Resolved Read
- Setup: Configure fuses_reg and cr_reg simulated values; connect a register read client.
- Action: Read sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3 and attempt to write an arbitrary value.
- Expected Result: Read returns cr_reg.val | fuses_reg.val; write has no effect / is rejected by the read-only descriptor.
- Verification Point: Validate read value equals ORed value; write does not change subsequent reads.

---

## Implementation Notes (for Simics Device Model Developers)

Key source files implementing the capability:
- srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml — templates for ports, c_pin_out usage and handler wiring. *Source: code map*
- srv-pm/code/hwrs-gen2/pwrgd-reset-pins.dml — pin/connect declarations. *Source: code map*
- srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml — register bank definitions and fields. *Source: code map*
- srv-pm/code/hwrs-gen2/hwrs-timer.dml — infra_timer implementation and phase handlers. *Source: code map*
- srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml — reset_sequencer_fsm, reset_seq_fsm_driver, and helper APIs. *Source: code map*
- srv-pm/code/hwrs-gen2/attributes.dml — attributes such as unwind_timeout_us, preamble_timeout_us, didt_timeout_us, strap attributes. *Source: code map*
- srv-pm/code/hwrs-gen2/hwrs-cbb-disable.dml, hwrs-ip-disable.dml — IP-disable logic applied by HWRS_SEQ_CONTROL writes. *Source: code map*
- srv-pm/code/hwrs-gen2/hwsync-d2d.dml — die-to-die sync handling used during DIDT/stagger phases. *Source: code map*

Template dependencies and patterns:
- pin_state_notifier templates for input ports implement signal_raise/signal_lower semantics.
- c_pin_out / c_pin_out_hap templates are used to drive outputs and emit HAP notifications; use c_pin_out.drive(pin, ASSERT/DEASSERT) pattern. *Source: pwrgd-reset-templates.dml*
- register templates support after_write and per-field write_action callbacks. Use these to implement side-effects that mirror fields to outputs and to call sequencer drivers. *Source: register snippets*
- infra_timer is a retriggerable one-shot event; use .post(delay_us) to schedule next phase and provide .cancel() when necessary. *Source: hwrs-timer.dml*

Extension / override points:
- after_write handlers in sb_cr.* register definitions: add or modify logic to change which outputs are driven or to introduce additional breakpoint conditions. *Source: sb_cr.HWRS_SEQ_CONTROL.after_write*
- reset_seq_fsm_driver and reset_sequencer_fsm_pass: to extend sequencer targets or guards add new targets and case transitions inside reset-sequencer-fsm.dml. *Source: reset-sequencer-fsm.dml*
- infra_timer phase handlers: to change phase sequencing or add new phase actions modify hwrs-timer.dml phase callbacks.
- Strap and fuses: strap attributes and fuses are modeled via strap_attr_u64 and saved attributes; changing strap definitions modifies sequencer branching. *Source: attributes.dml, hwrs-straps.dml*

Simulation fidelity notes / known differences from real HW:
- Timing is modeled via microsecond-scale timers; actual silicon may have additional wafer-to-wafer or analog variations not modeled.
- DIDT (dI/dt) effects are modeled as logical staggered toggles using didt_timeout_us; analog current-limited transitions are not modeled.
- Some side-effect sequencing (IP disables applied in phase-4) is implemented logically rather than enforcing peripheral-specific handshake completion; if remote devices are not connected the model still drives outputs but will not see real hardware responses.
- Certain register read/write protections (e.g., osdml_read_only) are honored at the DML level; however, behavior under concurrency or malformed sequences may differ from silicon.

*Sources: code map; register snippets; infra_timer descriptions*

---

## Platform Integration Notes (for Platform Architects)

Role in platform:
- The HWRS model coordinates platform-level power sequencing and reset transitions. It acts as the authoritative simulator-side component that receives power-good and reset assertions and drives downstream PM and reset signals used by CPU, IMH, CBB, SCU, and other subsystems. It also provides gate-level outputs (yyDIE_ENABLEx, vinf_pwrgood_rst_b, xxREFCLK_Rdy) that other platform devices consume. *Source: Working Flows*

Required PORT/CONNECT signal connections:
- Inputs that must be wired by the platform:
  - CPUPWRGD -> a source that asserts CPU power-good.
  - AUX_PWRGOOD -> auxiliary power-good source.
  - PLTRSTB (PLTRST) -> platform reset controller (active-low).
- Outputs that other devices expect:
  - punit_pm_unwind -> observed by power-management domain or a test observer.
  - hwrs_set_warm_reset_preamble_run -> observed by components that gate their warm-reset preamble behavior.
  - vinf_pwrgood_rst_b, xxREFCLK_Rdy, yyDIE_ENABLEx -> consumed by CPU/IMH/CBB/SCU and IP blocks.
  - cnic_s0_pwr_ok_int -> CNIC device interrupt line (HAP driven).
  - SCU handshake pins (scu_start_pmsync_handshake, scu_config_req) -> connected to SCU model. *Source: Interface Outputs & PORT nodes*

Dependencies on other capabilities / platform services:
- Sequencer progression can depend on strap/fuse attributes — the platform must configure strap attributes (e.g., fxr_disable_strap, partition_id, safe_mode_boot) to reflect the intended boot configuration. *Source: attributes.dml, hwrs-straps.dml*
- IP-disable resolved registers read fuses and CR values (requires fuse model or strap injection). *Source: ip_disable_resolved_cr*.
- Remote devices or platform models that implement handshake behaviors (SCU, IMH, CBB) should be connected to the corresponding CONNECT nodes to model complete handshakes. If not connected, HWRS will still drive outputs but no remote-side response will be observed. *Source: cpu-pwrgood-driven-sequencer-advance*

Configuration parameters that affect behavior:
- unwind_timeout_us, preamble_timeout_us, didt_timeout_us — control infra_timer phase delays (microsecond granularity). *Source: attributes.dml; hwrs-timer.dml*
- strap attributes: partition_id, safe_mode_boot, bist_enable and specialized straps such as fxr_disable_strap — influence sequencer branching and IP disable behavior. *Source: hwrs-straps.dml*
- fuses / emulated fuses register values used by IP-disable resolved registers and yyDIE_ENABLEx logic. *Source: ip-disable files*

Checkpointing and reset semantics:
- Many attributes are saved attributes and will be persisted in Simics checkpoints; some values (e.g., Cnic_S0_Pwr_Ok_Int) are intentionally sticky across hard_reset due to empty hard_reset() override. Validate behavior across checkpoint/hard_reset as part of platform validation. *Source: HWRS_DRIVE_PINS_PHASE_3_1 write description*

---

If you need a compact checklist of the minimal signals and registers to connect for an end-to-end boot-sequence simulation, or example DML snippets showing how to attach HAP observers to the c_pin_out HAPs for automated test harness verification, I can provide them.