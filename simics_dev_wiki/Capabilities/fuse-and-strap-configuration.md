[← Device Overview](overview.md)

---

# fuse-and-strap-configuration — dmr_imh_hwrs_fv

This page documents the fuse-and-strap sampling, resolved-strap register readouts, and HW reset/sequencer I/O implemented by the Simics DML device model dmr_imh_hwrs_fv. It is organized for three audiences (device model developers, software feature validators, and platform architects), with implementation- and behavior-level detail required to implement, validate and integrate the capability.

---

## Overview

- What is modeled: fuse-and-strap hardware sampled at instantiation, per-DWORD IP-disable fuse storage, SKU-feature fuses, legacy straps, and early-boot HWRS drive/observe pins used by the hardware reset sequencer. The model exposes:
  - saved attributes that represent persistent fuse/strap values (uint64_attr, strap_attr_u64, bool_attr),
  - resolved read-only software-visible registers that present the logical OR of software CRs and fuse DWORDs,
  - input notifiers for sequencer-driving signals and output pin drivers for reset / interrupt outputs.
- Role: supplies fused configuration to firmware/OS via resolved-read registers and drives/observes reset and power-related signals used during early boot sequencing.
- Scope (simulated vs stubbed):
  - Simulated: sampling of fuse/strap values as saved attributes; resolved register read behavior (CR OR fuse); forwarding of certain register writes to external pins; input pin notifications invoking reset-sequencer handlers.
  - Stubbed / not modeled: physical fuse blow mechanics, manufacturing-time fuse programming sequences, and fine-grained electrical/timing characteristics beyond event-notification (no analog timing model). The reset-sequencer FSM driver and some higher-level sequencing logic are implemented as driver code invoked from DML callbacks rather than full separate hardware units in this DML chunk. *Source: attributes.dml, hwrs-straps.dml, reset-sequencer-fsm.dml, sb_cr read_register snippets.*

Sources: *Source: srv-pm/code/hwrs-gen2/attributes.dml* · *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml* · *Source: srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml*

---

## How It's Simulated

- Fuse/strap values:
  - Modeled as Simics saved attributes: uint64_attr, strap_attr_u64, bool_attr (e.g., ip_disable_fuses_dword0.., sku_feature_dwordN, strap_legacy, procdis_n, fxr_disable_strap). Values are sampled/stored at instantiation and persist across checkpoint/restore. These saved attributes are read by register initialization and strap population logic. *Source: attributes.dml; State list*
- Resolved-read registers:
  - Implemented in the sb_cr register bank as read-only registers whose read_register delegates to a get() implementation that returns cr_reg.val | fuses_reg.val (software CR OR fuse DWORD). This produces a fused/resolved snapshot visible to software. Read-only registers (osdml_read_only or no set callbacks) discard write attempts. *Source: sb_cr DML read_register/get snippets; Register Side-Effects*
- Register-field side-effects:
  - Write_action / set callbacks on select register fields forward values to saved attributes or to output pins. Example: SKU_FEATURE_DWORD0.Svid_Not_Present.set(value) calls default(value) and—unless prevented by prevent_fuse_write_svid_not_present—propagates to HWRS_DIE_CONFIG.Svid_Not_Present.set(value). Example: HWRS_DRIVE_PINS_PHASE_3_1.Cnic_S0_Pwr_Ok_Int.set checks (this.val != value) and calls cnic_s0_pwr_ok_int_forward(value) to drive the pin. *Source: SKU_FEATURE_DWORD0 snippet; HWRS_DRIVE_PINS snippet*
- Inputs / outputs:
  - External inputs are pin_state_notifier ports that implement signal_raise/signal_lower; these update level.val and call on_change handlers used by reset sequencing logic (e.g., reset_seq_fsm_driver.on_change). Output pins use c_pin_out / c_pin_out_hap templates; callbacks raise/lower connected remote ports and emit HAPs (logged under pwrgd_reset). *Source: Interface Input/Output sections; c_pin_out usage notes*
- FSM / sequencing:
  - Reset sequencing progress is driven by on_change handlers invoked by pin_state_notifier updates or by register write callbacks. The FSM driver code consumes these notifications and may raise/lower outputs. The DML file reset-sequencer-fsm.dml contains the sequencer driver used by the device. *Source: reset-sequencer-fsm.dml*

Files of primary implementation: reg-banks-impl.dml, hwrs-ip-disable.dml, pwrgd-reset-templates.dml, hwrs-straps.dml, attributes.dml, reset-sequencer-fsm.dml. *Source: Code Map*

---

## Working Flow

This section describes the observable flows and the read/write semantics that software or a test harness will interact with.

1. Fuse early-boot completion (fuse-early-boot-complete)
   - Stimulus: fuse controller asserts fusectrl_early_boot_done (pin_state_notifier.signal_raise).
   - Effect sequence:
     1. pin_state_notifier.signal_raise updates level.val and invokes registered on_change handler.
     2. Handler calls reset_seq_fsm_driver.on_change → sequencer FSM advances early-boot state.
     3. Sequencer may drive outputs (e.g., early_boot_prim_rst_b or fusectrl_early_boot_side_rst_b) via c_pin_out callbacks and/or update resolved registers visible to software.
   - Observable results: connected remote pins change level; sb_cr resolved-read registers reflect fused values.

2. Drive S0 Power-OK interrupt (drive-power-ok-interrupt)
   - Stimulus: software writes HWRS_DRIVE_PINS_PHASE_3_1.Cnic_S0_Pwr_Ok_Int = 1 (or 0).
   - Effect sequence:
     1. Field write_action/set checks if new value differs (this.val != value).
     2. If changed, it calls cnic_s0_pwr_ok_int_forward(value) which raises/lowers the c_pin_out_hap and emits HAPs under pwrgd_reset.
   - Observable results: external consumer of cnic_s0_pwr_ok_int sees asserted/deasserted signal; HAP events logged.

3. SVID-absence propagation (SVID-absence-propagation)
   - Stimulus: software writes SKU_FEATURE_DWORD0.Svid_Not_Present = 1.
   - Effect sequence:
     1. Svid_Not_Present.set(value) calls default(value) to store new value.
     2. If prevent_fuse_write_svid_not_present guard permits, code forwards value to HWRS_DIE_CONFIG.Svid_Not_Present.set(value) updating die-level saved attribute.
   - Observable results: HWRS_DIE_CONFIG saved attribute updated; subsequent resolved reads and strap-dependent behavior will reflect the propagated value.

4. Resolved-read of IP disable masks
   - Read semantics: software reads sb_cr.IP_DISABLE_RESOLVED_CR_DWORDn (RO). read_register delegates to get(), which returns cr_reg.val | fuses_reg.val.
   - Writes to these registers are discarded / rejected as read-only.

Event scheduling: no timed scheduling is described in this capability beyond immediate callback invocation of on_change/write_action. No internal timers are defined in the provided DML data. *Source: Working Flows; Register Side-Effects*

---

## Register Map

| Register | Bank | Access Type | Reset Value | Write Side-Effect | Read Side-Effect |
|----------|------|-------------|-------------|-------------------|------------------|
| IP_DISABLE_RESOLVED_CR_DWORD0 | sb_cr | RO | N/A | Writes discarded / ignored | Returns cr_reg.val | fuses_reg.val (get() returns OR) — presents resolved IP-disable bitmap. *Source: sb_cr DML snippet* |
| IP_DISABLE_RESOLVED_CR_DWORD1 | sb_cr | RO | N/A | Writes ignored | Returns cr_reg.val | fuses_reg.val (resolved OR). *Source: Register Side-Effects* |
| IP_DISABLE_RESOLVED_CR_DWORD3 | sb_cr | RO | N/A | Writes rejected / discarded | get() returns cr_reg.val | fuses_reg.val (resolved fields incl. I3c_Spd_Disable, Tam_Disable). *Source: Register Side-Effects* |
| IP_DISABLE_RESOLVED_CR_DWORD4 | sb_cr | RO | N/A | Writes discarded | get() returns cr_reg.val | fuses_reg.val (Io_Stack_Disable, Mc_Stack_Disable, spare). *Source: Register Side-Effects* |
| IP_DISABLE_RESOLVED_CR_DWORD5 | sb_cr | RO | N/A | Read-only; writes discarded | get() returns cr_reg.val | fuses_reg.val (Spare_Disable[63:0]). *Source: Register Side-Effects* |
| IP_DISABLE_RESOLVED_CR_DWORD6 | sb_cr | RO | N/A | Writes rejected | get() returns cr_reg.val | fuses_reg.val (Core_Disable etc.). *Source: Register Side-Effects* |
| IP_DISABLE_RESOLVED_CR_DWORD7 | sb_cr | RO | N/A | Writes discarded | get() returns cr_reg.val | fuses_reg.val (resolved mask). *Source: Register Side-Effects* |
| SKU_FEATURE_DWORD0 | sb_cr | RW | N/A | Svid_Not_Present.set(value) calls default(value) and, unless prevented by prevent_fuse_write_svid_not_present, forwards to HWRS_DIE_CONFIG.Svid_Not_Present.set(value). Other fields stored. | Returns stored init values representing fuse-strapped SKU configuration. *Source: SKU_FEATURE_DWORD0 snippet* |
| HWRS_DRIVE_PINS_PHASE_3_1 | hwrs drive bank | RW | N/A | Cnic_S0_Pwr_Ok_Int.set checks (this.val != value); if changed calls cnic_s0_pwr_ok_int_forward(value) to raise/lower output pin. Other fields may drive other pins. | Typical read returns stored field values. *Source: HWRS_DRIVE_PINS snippet; Register Side-Effects* |

Notes:
- Reset values are not specified in the provided DML extracts — treat them as device/board configuration dependent (saved attribute initialization). *Source: attributes.dml*

---

## Interface Signals

| Signal | Direction | Interface Type | Trigger Condition | Action |
|--------|-----------|----------------|-------------------|--------|
| fusectrl_early_boot_side_rst_b | OUT (CONNECT) | c_pin_out / signal | HWRS early-boot sequencing logic asserts during early boot | Drive active-low sideband reset to external fuse controller; c_pin_out_hap emits HAPs under pwrgd_reset. *Source: Interface Output* |
| early_boot_prim_rst_b | OUT | c_pin_out / c_pin_out_hap | Driven by HWRS early-boot sequencing logic during early-boot | Drive downstream primary reset active-low; HAPs emitted. *Source: Interface Output* |
| cnic_s0_pwr_ok_int | OUT | signal / c_pin_out_hap | SW writes HWRS_DRIVE_PINS_PHASE_3_1.Cnic_S0_Pwr_Ok_Int (set -> forward) | Raise/lower CNIC S0 Power-OK interrupt to consumer; HAPs logged under pwrgd_reset. *Source: Interface Output* |
| imh2imh_hwsync_req_out | OUT | signal | Asserted by HWRS during inter-IMH sync (usage truncated) | Drive inter-IMH HW sync request line. *Source: Interface Output (truncated)* |
| fusectrl_early_boot_done | IN (PORT) | pin_state_notifier -> signal | External fuse controller asserts when early fuse loading completes | level.val updated; on_change handler invoked; reset sequencer FSM progresses. *Source: Interface Input* |
| dfxa_early_boot_done | IN | pin_state_notifier -> signal | DFXA subsystem asserts when its early boot completes | level.val updated; reset_seq_fsm_driver.on_change(true) invoked. *Source: Interface Input* |
| rclk_ip_ready | IN | pin_state_notifier -> signal | Reference clock IP asserts when clock stabilises | level.val updated; on_change handler invoked (used by reset sequencing). *Source: Interface Input* |
| cro_clk_valid | IN | pin_state_notifier -> signal | CRO asserts when its clock is valid | level.val updated; on_change handler invoked. *Source: Interface Input* |

Direction note: PORT = inbound to device (pin_state_notifier), CONNECT = outbound driven c_pin_out / signal.

---

## Behavioral Specification (for Software Feature Validators)

Each statement is testable by driving the stimulus and observing the result in the Simics model.

1. WHEN software reads sb_cr.IP_DISABLE_RESOLVED_CR_DWORDn (n = 0,1,3,4,5,6,7) -> THEN the returned 64-bit value equals (cr_reg.val | fuses_reg.val) where cr_reg.val is the last written software CR value and fuses_reg.val is the device's sampled fuse DWORD; writes to these registers are ignored. *Source: sb_cr read_register/get*
2. WHEN software writes HWRS_DRIVE_PINS_PHASE_3_1.Cnic_S0_Pwr_Ok_Int from 0→1 or 1→0 -> THEN the model forwards the change to the cnic_s0_pwr_ok_int output pin by calling cnic_s0_pwr_ok_int_forward(value) and the connected remote port sees the corresponding level change; repeated writes of the same value are no-ops. *Source: HWRS_DRIVE_PINS snippet*
3. WHEN software writes SKU_FEATURE_DWORD0.Svid_Not_Present = v -> THEN the field stores v locally and, unless prevent_fuse_write_svid_not_present is true, the model forwards v to HWRS_DIE_CONFIG.Svid_Not_Present.set(v) thereby updating the die-level saved attribute. *Source: SKU_FEATURE_DWORD0 snippet*
4. WHEN an external fuse controller asserts fusectrl_early_boot_done (pin_state_notifier.signal_raise) -> THEN the device updates the input port level, invokes the on_change handler which calls reset_seq_fsm_driver.on_change(), and the reset sequencer may drive early-boot outputs (e.g., early_boot_prim_rst_b asserted low). *Source: Working Flows*
5. WHEN a pin_state_notifier input (e.g., rclk_ip_ready or cro_clk_valid) signals a rising/stable event -> THEN level.val is updated and on_change handlers are invoked; the sequencer FSM transitions as appropriate (observable through subsequent output pin changes). *Source: Interface Input*
6. WHEN software attempts to write any IP_DISABLE_RESOLVED_CR_DWORDn register -> THEN the write is discarded/rejected and the register value returned on read remains the resolved OR of cr_reg and fuses_reg (i.e., CR portion is not updated through the RO resolved register). *Source: Register Side-Effects*

---

## Test Case Scenarios (for Software Feature Validators)

| Scenario | Setup | Action | Expected Result | Verification Point |
|---------|-------|--------|-----------------|--------------------|
| Fuse early-boot drives primary reset | Device instantiated with fusectrl_early_boot_done connected to test harness; early-boot sequencer enabled | Test harness calls fusectrl_early_boot_done.signal_raise() | early_boot_prim_rst_b is asserted (active-low) and HAP logged under pwrgd_reset | Observe connected remote's pin level and HAP logs |
| CNIC S0 Power-OK forwarding | Device instantiated; cnic_s0_pwr_ok_int connectable to test harness | SW writes HWRS_DRIVE_PINS_PHASE_3_1.Cnic_S0_Pwr_Ok_Int = 1 then = 0 | Remote port sees asserted then deasserted; write-action only executed when value changes | Read remote pin level; verify HAP emission and that repeated identical writes produce no new HAP |
| SVID absence propagation | Device instantiated with prevent_fuse_write_svid_not_present = false | SW writes SKU_FEATURE_DWORD0.Svid_Not_Present = 1 | HWRS_DIE_CONFIG.Svid_Not_Present saved attribute is set to 1 | Read HWRS_DIE_CONFIG.Svid_Not_Present attribute via model introspection |
| Resolved read reflects fuse OR CR | Device instantiated with ip_disable_fuses_dword0 = 0xA0A0, CR register cr_reg.val initially 0x0505 | SW writes software CR register (if writable CR exists) to 0x0F0F; SW then reads IP_DISABLE_RESOLVED_CR_DWORD0 | Read returns 0xA0A0 | Verify read_register result equals bitwise OR of CR and fuses; assert writes to resolved register were ignored |
| Prevented SVID write guard | Device instantiated with prevent_fuse_write_svid_not_present = true | SW writes SKU_FEATURE_DWORD0.Svid_Not_Present = 1 | HWRS_DIE_CONFIG.Svid_Not_Present remains unchanged | Verify HWRS_DIE_CONFIG attribute unchanged; field value stored locally but not propagated |

Notes for testers:
- Use model introspection APIs to read saved attributes (e.g., HWRS_DIE_CONFIG) and to observe c_pin_out HAPs and remote port levels.
- Ensure that resolved-register read verification compares with the OR of the known CR value and the configured saved fuse value.

---

## Implementation Notes (for Simics Device Model Developers)

- Key DML files:
  - Attributes and straps: srv-pm/code/hwrs-gen2/attributes.dml, srv-pm/code/hwrs-gen2/hwrs-straps.dml. *Source: Code Map*
  - Register banks and resolved register logic: srv-pm/code/hwrs-gen2/reg-banks-impl.dml, srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml, srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml. *Source: Code Map*
  - Reset sequencing and templates: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml, srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml. *Source: Code Map*
- Template dependencies and inheritance:
  - c_pin_out / c_pin_out_hap templates are used for outputs; pin_state_notifier for inputs. Register-field templates use reg_fld_binding and write_action/set hooks.
  - Resolved registers implement read_register -> get() override to return cr_reg.val | fuses_reg.val.
- Extension / override points:
  - To add new fused-resolved registers: add a sb_cr register in the reg-banks with read_register delegating to get() and provide a fuses_reg binding to the appropriate saved attribute.
  - To forward additional register fields to saved attributes or pins: implement set()/write_action on the reg_fld and call the appropriate HWRS_DIE_CONFIG.*.set(value) or c_pin_out forward function; reuse the equality guard pattern (if (this.val != value) ...).
  - To hook additional input signals: add pin_state_notifier ports and register on_change handlers that call into reset_seq_fsm_driver or custom handlers.
- Read/write behavior:
  - Read-only resolved registers should be declared osdml_read_only (or not implement set callbacks) so writes are ignored.
  - For SKU writes with forwarding, respect the prevent_fuse_write_* guards where provided.
- Simulation fidelity / known differences:
  - Fuses and straps are static saved attributes sampled at instantiation — there is no modelling of fuse burning processes or production programming flows.
  - Timing is event-driven (immediate callbacks); there are no detailed analog or electrical timing effects.
  - The reset FSM driver is invoked via on_change handlers — the DML chunk exposes hook points but some sequencing logic may be implemented as driver code outside the register bank definitions. *Source: reset-sequencer-fsm.dml; attributes.dml*
- Recommended testing hooks:
  - Emit HAPs from c_pin_out_hap callbacks (already present) for external observers and validation tests.
  - Expose HWRS_DIE_CONFIG saved attributes so test harnesses can assert propagation state.

Sources: *Source: srv-pm/code/hwrs-gen2/reg-banks-impl.dml* · *Source: srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml* · *Source: snips: SKU_FEATURE_DWORD0, HWRS_DRIVE_PINS, sb_cr read_register*

---

## Platform Integration Notes (for Platform Architects)

- Role in platform:
  - The HWRS fuse-and-strap configuration device is the authoritative provider of fused/strapped platform configuration to firmware and of early-boot reset / interrupt outputs required for platform bring-up and power sequencing.
- Required signal connections (examples and expected counterpart devices):
  - fusectrl_early_boot_done (INPUT) ← fuse controller early-boot-done output.
  - dfxa_early_boot_done (INPUT) ← DFXA subsystem early-boot output.
  - rclk_ip_ready, cro_clk_valid (INPUTs) ← clock IPs that assert stabilized/valid signals.
  - early_boot_prim_rst_b (OUTPUT) → primary reset consumer device(s) on the downward reset chain.
  - fusectrl_early_boot_side_rst_b (OUTPUT) → fuse controller side-reset input.
  - cnic_s0_pwr_ok_int (OUTPUT) → CNIC S0 interrupt consumer.
  - imh2imh_hwsync_req_out (OUTPUT) → peer IMH device(s) for HW sync (when used).
  - All outputs are c_pin_out / signal types that should be connected to corresponding input ports on target devices.
  - Remote ports should be present in the platform topology to observe HAPs and pin levels. *Source: Interface Output/Input*
- Dependencies:
  - Reset sequencing relies on reset-sequencer-fsm code and pwrgd-reset templates; platform must include those driver templates and the pwrgd-reset HAP consumer if end-to-end validation is required. *Source: Code Map*
  - Some feature behavior depends on the HWRS_DIE_CONFIG saved-attribute aggregation; platform-level aggregation of die-level attributes should be consistent to observe propagated SKU changes.
- Configuration parameters impacting behavior:
  - Saved attributes used to model fuse/strap values: ip_disable_fuses_dword0/1/4/6/7/8, sku_feature_dword2/3/4/7/8/9, strap_legacy, procdis_n, fxr_disable_strap, lg_spare_tx_en_b_5_0, trigger_cold_rst_exit_done, etc. These are set at device instantiation to represent board/programmed state. *Source: State & FSM Behavior list*
  - guards such as prevent_fuse_write_svid_not_present control whether software writes propagate to die-level config.
- Integration recommendations:
  - Connect pin_state_notifier inputs to the actual model(s) that drive those signals so the reset FSM can progress.
  - Ensure consumers of c_pin_out_hap outputs subscribe to the pwrgd_reset HAP stream for observability in tests.
  - Initialize saved fuse/strap attributes to values matching the intended board/sku configuration so resolved-read register behavior is correct from the first read.

Sources: *Source: Code Map* · *Source: Interface Input/Output* · *Source: State & FSM Behavior*

---

If you need concrete DML examples for adding a new resolved register, a write-forwarding reg_fld, or a sample test script that asserts a pin HAP and checks a saved attribute, I can produce templates and example Simics commands.