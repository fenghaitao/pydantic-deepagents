[← Device Overview](overview.md)

---

# debug-and-integration (dmr_imh_hwrs_fv) — Capability Wiki

## Overview
This capability models the HWRS "debug-and-integration" functions implemented in the Simics DML device dmr_imh_hwrs_fv. It provides early-boot debug/external handshakes, Q-channel power-management signaling for the NAC subsystem, a notification output indicating SCU configuration completion, and a sampled BIST hardware strap. The model is focused on behavioral correctness of pin-level interactions visible to platform-level firmware and debug sequencers; it does not attempt to model analog timing or detailed electrical characteristics.

Scope:
- Simulated: digital input signal sampling and on-change callbacks for early-boot and fuse/control signals; active-low Q-channel request output with runtime guards; SCU configuration-done output using HAP-driven callbacks; sampled BIST strap as a saved attribute visible to drivers/others.
- Stubbed / not modeled: register-level side-effects and timed event sequencing beyond immediate callback-driven behavior; analog/electrical properties and low-level reset domain timing details. (No Register Side-Effects data is available in the source set.)

Source references:
- Implementation files referenced in the DML: srv-pm/code/hwrs-gen2/hwrs-straps.dml, srv-pm/code/hwrs-gen2/hwrs-nac-pins.dml, srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml, srv-pm/code/hwrs-gen2/reset-sequencer-pin-cmds.dml. *Source: srv-pm/code/hwrs-gen2/*

---

## How It's Simulated
The DML uses a combination of Simics templates and saved attributes to model behavior:

- Input signals:
  - early_boot_debug_exit, endebug_early_boot_done, fusectrl_early_boot_done, nac_soc_qch_accept are implemented with the pin_state_notifier template. Each provides signal_raise()/signal_lower() operations which:
    - update a saved boolean level (.level.val),
    - call notify_level_change() on transitions,
    - dispatch a configured on_change(level) callback to execute DML-defined behavior. *Source: pin_state_notifier-derived ports (multiple source_refs)*

- Output signals:
  - scu_config_done is implemented using c_pin_out which inherits c_pin_out_hap. This template uses HAP (hook/handler) callbacks to drive remote pin interfaces and does null-object checks and HAP sequencing safeguards. It is grouped under the "pwrgd_reset" log group for reset sequencing traces. *Source: c_pin_out / c_pin_out_hap references*
  - nac_ss_qreqn is implemented with c_pin_out_nac. This template includes runtime guards (requires device not be a primary IMH, and that it is a CNIC IOH) and a saved boolean saved_level that suppresses redundant drives to the remote pin. *Source: c_pin_out_nac template description*

- Persistent configuration:
  - strap_bist_enable is modeled as a saved attribute via strap_attr_u64 mapped to POC_STRAPS.Bist_Enable. This models a sampled hardware strap read at instantiation or configuration time. *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml*

Simulation fidelity notes:
- Level changes are treated as instantaneous (no scheduled delayed events) and processed synchronously via HAP/callbacks.
- No register-side effects or event scheduling information is modeled or available in the data set.
- nac_soc_qch_accept behavior is modeled as an inverted write to an internal Assert_Nac_Qack field (0 when input asserted, 1 when deasserted).

---

## Working Flow
This section describes state changes, signal interactions, and the observer-visible behavior.

1) early-boot-debug-exit flow
- Trigger: external debug/boot controller calls early_boot_debug_exit.signal_raise()
- Behavior:
  - signal_raise() sets early_boot_debug_exit.level.val = true if it was false,
  - notify_level_change(true) is invoked,
  - configured on_change(true) callback runs.
- Observable result: port.level.val == true and the on_change callback-side effects are visible to any observers or other DML logic. *Source: pin_state_notifier port description*

2) endebug-early-boot-done flow
- Trigger: endebug_early_boot_done.signal_raise() from endebug sequencer
- Behavior identical to other pin_state_notifier-based inputs: sets level, calls notify_level_change(), invokes on_change(true).

3) nac-qchannel-accept flow
- Trigger: nac_soc_qch_accept.signal_raise() from SoC Q-channel controller
- Behavior:
  - signal_raise() updates nac_soc_qch_accept.level.val and calls notify_level_change(true),
  - on_change(true) callback writes the inverted level to Assert_Nac_Qack (i.e., if input is asserted, Assert_Nac_Qack = 0; if input deasserted, Assert_Nac_Qack = 1).
- Observable result: Assert_Nac_Qack internal field updated and visible to consumers. *Source: capability analysis "nac-qchannel-accept" flow*

4) SCU configuration completion (scu_config_done)
- Trigger: internal HAP/callback posted by DML logic indicating SCU configuration completed (often sequencer-driven in reset/power-up flows)
- Behavior:
  - c_pin_out_hap logic raises or lowers the remote pin via the configured HAP callbacks,
  - null-object checks prevent drive when no remote connected.
- Observable result: remote pin for scu_config_done reflects the posted HAP-driven level. *Source: c_pin_out_hap description*

5) NAC QREQn output (nac_ss_qreqn)
- Trigger: model-invoked drive logic (e.g., sequencer or DML action) that requests QREQn asserted/deasserted
- Behavior:
  - c_pin_out_nac enforces runtime guards (device must not be primary IMH and must be CNIC IOH),
  - saved_level prevents redundant remote pin writes,
  - when allowed, remote active-low QREQn pin is driven accordingly.
- Observable result: remote NAC QREQn pin reflects last accepted drive level; no effect if runtime guards fail or drive is redundant. *Source: c_pin_out_nac description*

Registers involved:
- No register map entries or register side-effects are present in the provided data. Strap_bist_enable is modeled as a saved attribute mapped to POC_STRAPS.Bist_Enable rather than a read/write register. (See Register Map section.)

Event scheduling:
- No timers or deferred actions are modeled; all transitions are processed synchronously through notify_level_change()/HAP callbacks.

---

## Register Map
No register read/write side-effects or device registers are modeled in the provided capability data. The only persistent configuration element is the sampled strap:

| Register | Bank | Access Type | Reset Value | Write Side-Effect | Read Side-Effect |
|----------|------|-------------|-------------|-------------------|------------------|
| POC_STRAPS.Bist_Enable (modeled) | strap storage | RO (sampled strap) | device-configured value | N/A (sampled at instantiation/configuration) | Read returns sampled strap value (strap_bist_enable saved attribute) |

Notes:
- strap_bist_enable is exposed as a saved attribute (strap_attr_u64) bound to POC_STRAPS.Bist_Enable. *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml*

---

## Interface Signals
(PORT = IN to this device; CONNECT = OUT from this device)

| Signal | Direction | Interface Type | Trigger Condition | Action |
|--------|-----------|----------------|-------------------|--------|
| early_boot_debug_exit | PORT (IN) | signal (pin_state_notifier) | upstream debug/boot controller calls signal_raise()/signal_lower() | On rising transition: set .level.val true, call notify_level_change(true), invoke configured on_change(true) callback. *Source: pin_state_notifier port data* |
| endebug_early_boot_done | PORT (IN) | signal (pin_state_notifier) | endebug sequencer toggles its early-boot-complete line | On rising: update level, notify_level_change(), invoke on_change handler. *Source: port description* |
| fusectrl_early_boot_done | PORT (IN) | signal (pin_state_notifier) | fuse controller signals early boot completion | As above: set level, notify, execute on_change callback. *Source: port description* |
| nac_soc_qch_accept | PORT (IN) | signal (pin_state_notifier) | SoC Q-channel controller toggles QACCEPTn line | On change: update level, on_change writes inverted value to internal Assert_Nac_Qack; consumers observe updated ack. *Source: nac-qchannel-accept flow* |
| nac_ss_qreqn | CONNECT (OUT) | pin (c_pin_out_nac) | model-invoked drive logic requests QREQn change, subject to runtime guards | Drive active-low NAC Subsystem QREQn pin when allowed; saved_level suppresses redundant drives; guarded by "not primary IMH" and "CNIC IOH" checks. *Source: c_pin_out_nac description* |
| scu_config_done | CONNECT (OUT) | pin (c_pin_out / c_pin_out_hap) | DML posts HAP/callback indicating SCU configuration complete | c_pin_out_hap raises/lowers remote SCU config done pin via HAP; null checks and HAP sequencing enforced. *Source: c_pin_out_hap description* |

---

## Behavioral Specification (for Software Feature Validators)
Each statement is precise and testable from the point of view of an observer (firmware/driver or testbench invoking signal operations).

1. WHEN an upstream debug/boot controller invokes early_boot_debug_exit.signal_raise() -> THEN early_boot_debug_exit.level.val becomes true and the port's on_change(true) callback is invoked (callback-side effects must be visible to observers).
2. WHEN endebug_early_boot_done.signal_raise() is called -> THEN endebug_early_boot_done.level.val becomes true and the port's on_change(true) callback runs.
3. WHEN nac_soc_qch_accept.signal_raise() is called -> THEN the model writes Assert_Nac_Qack = 0 (inverted write), and any consumers reading Assert_Nac_Qack see the updated value immediately.
4. WHEN the model posts the HAP/callback that marks SCU configuration complete -> THEN the scu_config_done CONNECT toggles to the asserted level (remote pin driven) unless no remote is attached; repeated posts that request the same level should not cause redundant remote writes only if c_pin_out_hap logic handles suppression.
5. WHEN the DML attempts to drive nac_ss_qreqn -> THEN the drive is executed only if the runtime guard conditions are satisfied (device is not primary IMH and device role is CNIC IOH); otherwise the drive is suppressed and remote pin remains unchanged.
6. WHEN the device is instantiated with strap_bist_enable set -> THEN reads of POC_STRAPS.Bist_Enable return the configured sampled strap value (strap_bist_enable) for the duration of simulation (unless configuration APIs modify saved attributes).

---

## Test Case Scenarios (for Software Feature Validators)

| Scenario | Setup | Action | Expected Result | Verification Point |
|---------|-------|--------|-----------------|--------------------|
| Early boot debug exit callback | Attach a test observer that records invocation of the early_boot_debug_exit on_change handler; ensure port present | Call early_boot_debug_exit.signal_raise() | early_boot_debug_exit.level.val == true; observer recorded on_change(true) invocation | Read port.level.val from model; observer callback log contains entry |
| Endebug early-boot completion | Attach observer for endebug on_change; ensure port present | Call endebug_early_boot_done.signal_raise() | endebug_early_boot_done.level.val == true; on_change handler executed | Read port.level.val; observer log contains callback |
| NAC Q-channel accept updates Assert_Nac_Qack | Instrument internal Assert_Nac_Qack or provide consumer that reads it | Call nac_soc_qch_accept.signal_raise(); then signal_lower() | After raise: Assert_Nac_Qack == 0; after lower: Assert_Nac_Qack == 1 | Read Assert_Nac_Qack after each transition |
| SCU config done drive via HAP | Connect a remote mock pin which records drive operations; trigger the HAP/callback that signals SCU config complete | Post the SCU-complete HAP/callback in the model | Remote pin is driven to the asserted level; HAP call recorded; no drive if no remote attached | Check remote pin state and recorded HAP invocations; verify null-object path if remote unconnected |
| NAC QREQn runtime guard enforcement | Configure device role flags: set device as primary IMH or not-CNIC IOH; attach mock remote pin | Attempt to drive nac_ss_qreqn active | If device is primary IMH or not CNIC IOH: no remote drive; otherwise remote pin driven and saved_level updated | Check remote pin drive log and the saved_level (if exposed) | 

Notes for verification:
- Where internal fields (Assert_Nac_Qack, saved_level) are not directly visible via the simulation API, provide small DML accessor bindings or enable temporary observation hooks for test harness use.
- Tests should toggle both raise() and lower() to validate inverted or level semantics.

---

## Implementation Notes (for Simics Device Model Developers)
Key DML source files:
- srv-pm/code/hwrs-gen2/hwrs-straps.dml — strap_bist_enable and strap mappings. *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml*
- srv-pm/code/hwrs-gen2/hwrs-nac-pins.dml — NAC pin definitions including c_pin_out_nac usage. *Source: srv-pm/code/hwrs-gen2/hwrs-nac-pins.dml*
- srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml — power/reset group for c_pin_out_hap and logging. *Source: srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml*
- srv-pm/code/hwrs-gen2/reset-sequencer-pin-cmds.dml — reset-sequencer driven pin commands that may interact with scu_config_done and NAC sequences. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-pin-cmds.dml*

Template dependencies and inheritance chain:
- pin_state_notifier (input signal template)
  - Provides signal_raise(), signal_lower(), .level.val saved boolean, notify_level_change(), and on_change(level) callback hook. Use for all input ports (early_boot_debug_exit, endebug_early_boot_done, fusectrl_early_boot_done, nac_soc_qch_accept).
- c_pin_out / c_pin_out_hap (output pin with HAP integration)
  - Use for scu_config_done; supports HAP-based drive callbacks, null-object checks and grouping for reset logs.
- c_pin_out_nac (output pin with NAC-specific runtime guards)
  - Use for nac_ss_qreqn; contains saved_level suppression and runtime guards (primary IMH / CNIC IOH checks).
- strap_attr_u64
  - Used to implement strap_bist_enable bound to POC_STRAPS.Bist_Enable.

Extension / override points:
- on_change callbacks on pin_state_notifier ports: extend or replace to implement additional behavior, side effects, or inter-device notifications.
- c_pin_out_hap HAP hooks: add additional sequencing or logging by attaching to the same HAP or by overriding template callbacks.
- c_pin_out_nac guard logic: modify or parameterize the guard conditions (e.g., which role flags are checked) by changing the c_pin_out_nac instantiation or its runtime checks.
- Expose internal fields (Assert_Nac_Qack, saved_level) via temporary DML accessors or attributes for unit testing.

Simulation fidelity / known differences from hardware:
- The model treats pin transitions and callback effects as immediate and synchronous — real hardware may present delays, metastability, or asynchronous crossing boundaries.
- No per-pin electrical or rise/fall time modeling; no bus contention logic.
- Register-level side-effects are not present in the current DML snapshot (no R/W/W1C behavior modeled).
- The inverted mapping of nac_soc_qch_accept to Assert_Nac_Qack is modeled as an immediate write in the on_change callback; confirm with hardware spec if any handshake or timing constraints are required.

Development tips:
- When adding new behavior that should be observable to test harnesses, prefer adding a saved attribute or HAP emission rather than hidden internal writes.
- To avoid frequent redundant remote writes, rely on the saved_level suppression already present in c_pin_out_nac and similar templates.

---

## Platform Integration Notes (for Platform Architects)
Role in platform:
- Provides early-boot integration hooks between IMH (Integrated Management Hub) elements, SCU configuration sequencing, fuse controller completion signals, and the SoC Q-channel power management interface (NAC Q-channel). It is used by reset/power sequencers and debug firmware to coordinate early platform initialization.

Required connections (typical counterparts):
- early_boot_debug_exit (PORT/IN) <- upstream debug or boot controller (e.g., debug sequencer, early boot manager).
- endebug_early_boot_done (PORT/IN) <- endebug sequencer output.
- fusectrl_early_boot_done (PORT/IN) <- fuse controller early-boot-done output.
- nac_soc_qch_accept (PORT/IN) <- SoC Q-channel controller QACCEPTn signal source.
- nac_ss_qreqn (CONNECT/OUT) -> NAC subsystem QREQn input (active-low).
- scu_config_done (CONNECT/OUT) -> System Control Unit or reset sequencer that observes SCU configuration completion.

Dependencies on other device capabilities or platform services:
- Proper behavior of nac_ss_qreqn is conditional on the device role and platform configuration: the c_pin_out_nac template performs runtime checks requiring the device is not a primary IMH and that it is configured as a CNIC IOH. Platform-level role flags or properties must be set accordingly for the NAC QREQn to be driven. *Source: c_pin_out_nac runtime guards*
- HAP/callback infrastructure must be available and the reset/power sequencing HAPs must be wired for scu_config_done to effect sequencer transitions.
- strap_bist_enable is a sampled strap and must be set at instantiation or via DML configuration before tests that depend on it run.

Configuration parameters that affect this capability:
- strap_bist_enable (strap_attr_u64 bound to POC_STRAPS.Bist_Enable): determines sampled BIST enable strap state visible to firmware. *Source: hwrs-straps.dml*
- Device role flags (primary IMH vs. non-primary; CNIC IOH role): control whether c_pin_out_nac will drive nac_ss_qreqn.
- Presence/absence of remote pin connections: c_pin_out_hap and c_pin_out_nac behave differently (null-object checks, no-op on missing remote).

Recommended platform wiring checklist:
- Verify that all input PORTs are connected to the intended producers in the platform model (debug sequencer, endebug sequencer, fuse controller, Q-channel controller).
- Ensure appearance of the SCU consumer for scu_config_done if subsequent reset sequencing must observe configuration completion.
- Configure device role properties (IMH primary flag, CNIC IOH flag) prior to running any test that expects nac_ss_qreqn activity.

---

If you need: code snippets for typical DML instantiations, small test harness scripts to exercise these ports from a Simics Python testbench, or suggested DML accessor bindings to expose Assert_Nac_Qack / saved_level for validation, I can provide them.