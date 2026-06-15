[← Device Overview](overview.md)

---

# pcie-and-io-reset — IMH/HWRS capability

Overview
--------
This capability models the IMH/HWRS PCIe and IO reset sequencing and CNIC-specific reset routing used to drive NAC/IOH reset and power-good outputs, and to accept a ready-for-enumeration input from an upstream controller.

Modeled outputs (active-low unless noted):
- nac_sys_rst_n
- nac_early_boot_rst_b
- nac_pwrgood_rst_b
- nac_inf_iosfsb_rst_b
- nac_hif_pcie0_perst_n0
- nac_inf_rstbus_rst_b
- nac_sn2sfi_rst_n
- nac_sn2sfi_rst_pre_ind_n (pre-indication line)
- vnn_soc_group_pwrgood_rst_b (power-good reset output)
- vin_pwrgood_rst_b (power-good reset output)

Modeled input (PORT):
- nac_ready_for_enum (ready-for-enumeration / input signal)

Scope:
- Simics models the reset assertion/deassertion sequencing (including time-delayed pre-indication → actual reset), CNIC role gating, saved-pin level suppression of redundant drives, and sequencer-driven multi-phase reset actions.
- Strap/configuration values (is_ioh_with_cnic, strap_dmi_mode_override, sku_feature_* and related strap attributes) are simulated as read-only attributes controlling behavior.
- The pre-indication → reset delay is implemented as a fixed 0.001 s (1 ms) after-handler in the model.
- No register map or MMIO side-effects are modeled by this capability (register side-effects: not available).

Source: DML implementation files: srv-pm/code/hwrs-gen2/* (see Implementation Notes).

How It's Simulated
------------------
Implementation constructs:
- CONNECT templates: c_pin_out_nac, c_pin_out, and c_pin_out_hap implement output pins. Each CONNECT instance stores a saved boolean level and provides raise()/lower() helpers which:
  - suppress redundant remote calls when the saved level is unchanged,
  - apply role/strap guards (for CNIC/IMH role),
  - invoke connected ports or HAP callbacks when a permitted transition occurs.
  Source: srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml
- PORT template: pin_state_notifier implements the nac_ready_for_enum input. It exposes signal_raise()/signal_lower() which invoke on_change handlers on edges; the rising edge triggers the reset sequencer driver callback.
  Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml
- Reset sequencer FSM: reset_seq_fsm driver advances sequencing state when invoked by the nac_ready_for_enum rising edge or other internal events. Sequencer entry/phase actions call c_pin_out_nac raise()/lower() to assert/deassert outputs per phase.
  Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml, srv-pm/code/hwrs-gen2/reset-sequencer-pin-cmds.dml
- Event scheduling: pre-indication → actual SN2SFI reset is implemented using Simics after handlers. A pre-indication drive schedules a one-shot after 0.001 s callback to call nac_sn2sfi_rst_n.lower().
  Source: srv-pm/code/hwrs-gen2/reset-sequencer-pin-cmds.dml

Guard/configuration attributes:
- is_ioh_with_cnic (bool_attr): gates CNIC-specific outputs (only drive CNIC outputs when true).
- strap_dmi_mode_override (uint64_attr), sku_feature_dword5/8 (uint64_attr), lg_spare_tx_en_b_5_0 (strap_attr_u64): influence sequencer or output gating (product SKU and lane/tx enables).
  Source: srv-pm/code/hwrs-gen2/attributes.dml, srv-pm/code/hwrs-gen2/hwrs-straps.dml

What is stubbed / simplified:
- No MMIO register side-effects or read/write registers are modeled for this capability.
- The SN2SFI pre-indication delay is a fixed 1 ms in Simics rather than modeled as asynchronous electrical propagation — it is implemented as a software timer.
- The implementation exposes strap/sku values as static attributes at instantiation (no dynamic sampling logic).

Working Flow
------------
System-level behavior is driven either by an upstream controller asserting nac_ready_for_enum or by software/agents calling specific connect operations. The sequencer implements multi-phase reset behavior and CNIC-aware gating.

1) nac-sn2sfi-reset-preindication (pre-indication → SN2SFI reset)
- Trigger: external agent calls nac_sn2sfi_rst_pre_ind_n.raise() on the CONNECT.
- Steps:
  1. c_pin_out_nac::raise() for nac_sn2sfi_rst_pre_ind_n checks the saved level and role guards (is_ioh_with_cnic && !is_primary_imh). If permitted, it updates the saved level and drives the connected downstream port.
  2. The implementation schedules an after-handler for 0.001 s.
  3. After 0.001 s the callback calls nac_sn2sfi_rst_n.lower(), which runs c_pin_out_nac::lower(), checks guards and drives the downstream SN2SFI reset line (active-low asserted).
- Result: downstream nac_sn2sfi_rst_n is asserted 1 ms after pre-indication.

2) nac-ready-for-enumeration-driven sequencer
- Trigger: upstream controller calls nac_ready_for_enum.signal_raise().
- Steps:
  1. pin_state_notifier.on_change() detects the rising edge and invokes the reset_seq_fsm driver callback (sequencer entry).
  2. The sequencer advances state and posts sequencing events / entry actions that issue c_pin_out_nac.raise()/lower() calls for pins like nac_hif_pcie0_perst_n0 and nac_inf_rstbus_rst_b. Each connect method applies role/strap guards (e.g., is_ioh_with_cnic, !is_primary_imh).
  3. Sequencer may schedule additional timed events (including the SN2SFI pre-indication handler).
- Result: PCIe PERST# and NAC reset-bus lines are asserted/deasserted as per sequencer phases; software can observe the progression via outputs and device state.

3) deep-warm-reset-assert (sequencer-driven deep warm reset)
- Trigger: sequencer enters deep-warm-reset phase.
- Steps:
  1. Sequencer entry action calls nac_sys_rst_n.lower(), nac_inf_iosfsb_rst_b.lower(), nac_pwrgood_rst_b.lower() through the c_pin_out_nac API.
  2. Each c_pin_out_nac.lower() checks saved level and guards, updates level and notifies connected ports/HAPs as required.
- Result: NAC/IOH resets and IOSFSB reset are asserted (active-low) and connected devices receive reset notifications via HAP or connected port invocation.

State & redundancy suppression
- Each CONNECT keeps a saved bool level. raise()/lower() operations suppress redundant remote calls when the level would not change; they also log "no-op" when redundant.
- Role/strap guard checks are evaluated at each raise()/lower() call to prevent driving outputs on IMH die variants where pin is not applicable.

Event scheduling
- SN2SFI pre-indication schedules a re-triggerable one-shot after 0.001 s that asserts (lowers) nac_sn2sfi_rst_n. New pre-indications reschedule the handler implicitly by executing the scheduling code path again.
- No explicit cancel interface is modeled for the after-handler.

Interface Signals
-----------------
| Signal | Direction | Interface Type | Trigger Condition | Action |
|--------|-----------|----------------|-------------------|--------|
| nac_ready_for_enum | IN (PORT) | signal (pin_state_notifier) | External controller calls signal_raise() | pin_state_notifier.on_change() invokes reset_seq_fsm driver callback on rising edge; sequencer advances and drives outputs. Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml |
| nac_sn2sfi_rst_pre_ind_n | OUT (CONNECT) | c_pin_out_nac | Model code calls raise()/lower() (software/agent) | Drives pre-indication to downstream SN2SFI; schedules 0.001 s after-handler to call nac_sn2sfi_rst_n.lower(). Source: srv-pm/code/hwrs-gen2/reset-sequencer-pin-cmds.dml |
| nac_sn2sfi_rst_n | OUT (CONNECT) | c_pin_out_nac | After-handler or direct sequencer calls lower()/raise() | Asserts/deasserts SN2SFI reset line toward downstream device. Source: srv-pm/code/hwrs-gen2/reset-sequencer-pin-cmds.dml |
| nac_hif_pcie0_perst_n0 | OUT (CONNECT) | c_pin_out_nac / c_pin_out_hap | Sequencer phase actions | Drives PCIe PERST# for downstream device; may call HAP callbacks on level change. Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml |
| nac_inf_rstbus_rst_b | OUT (CONNECT) | c_pin_out_nac | Sequencer phase actions | Drives NAC reset bus line (active-low). Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml |
| nac_sys_rst_n, nac_early_boot_rst_b, nac_pwrgood_rst_b, nac_inf_iosfsb_rst_b | OUT (CONNECT) | c_pin_out_nac | Sequencer entry actions (e.g., deep warm reset) | Drive NAC/IOSFSB/power-good reset outputs (active-low). Source: srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml |
| vnn_soc_group_pwrgood_rst_b, vin_pwrgood_rst_b | OUT (CONNECT) | c_pin_out_nac | Sequencer or power-good events | Power-good reset outputs driven per model logic. Source: srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml |

Behavioral Specification (testable WHEN -> THEN)
-------------------------------------------------
1. WHEN nac_sn2sfi_rst_pre_ind_n.raise() is invoked on the device AND is_ioh_with_cnic == true AND device is not primary IMH -> THEN the device schedules an after-handler and within 0.001 s nac_sn2sfi_rst_n becomes asserted (active-low).
2. WHEN nac_sn2sfi_rst_pre_ind_n.raise() is invoked repeatedly faster than 1 ms -> THEN each invocation re-triggers/reschedules the one-shot after-handler so that nac_sn2sfi_rst_n assertion occurs 1 ms after the last pre-indication (model re-scheduling behavior is re-triggerable).
3. WHEN an external controller asserts nac_ready_for_enum.signal_raise() -> THEN pin_state_notifier.on_change() invokes the reset sequencer (reset_seq_fsm) and the sequencer issues per-phase outputs (e.g., nac_hif_pcie0_perst_n0 lowered or raised) according to sequencer state, subject to CNIC/IMH role guards.
4. WHEN the sequencer enters the deep warm reset phase -> THEN nac_sys_rst_n, nac_inf_iosfsb_rst_b, and nac_pwrgood_rst_b are asserted (lowered) and connected HAP callbacks (if present) are invoked on those level changes.
5. WHEN a c_pin_out_nac.raise() or lower() is called and the requested logical level equals the saved bool level -> THEN the implementation performs no remote port drive and logs a no-op (i.e., redundant drives are suppressed).

Test Case Scenarios (for Software Feature Validators)
----------------------------------------------------
| Scenario | Setup | Action | Expected Result | Verification Point |
|---------|-------|--------|-----------------|--------------------|
| SN2SFI pre-indication causes reset after delay | Device instantiated with is_ioh_with_cnic=true, is_primary_imh=false. Upstream ready signal inactive. | Call nac_sn2sfi_rst_pre_ind_n.raise() | Within 1 ms, nac_sn2sfi_rst_n is asserted (active-low). | Observe nac_sn2sfi_rst_n port state transition; timestamp delta ≈ 0.001 s. |
| Re-triggering pre-indication postpones reset | Same setup as above. | Call pre_ind.raise(); 0.5 ms later call pre_ind.raise() again. | nac_sn2sfi_rst_n asserts ~1 ms after the last pre_ind.raise() (≈1.5 ms after first). | Verify that assertion time is ≈0.001 s after the second raise. |
| Ready-for-enumeration starts sequencer and drives PERST# | Device instantiated; is_ioh_with_cnic=true. PCIe downstream monitor installed. | Call nac_ready_for_enum.signal_raise() | Sequencer runs; nac_hif_pcie0_perst_n0 is driven according to sequencer phase (asserted or deasserted per phase) and subsequent reset-bus signals are driven. | Observe nac_hif_pcie0_perst_n0 transitions and optional HAP notifications; verify sequence order per sequencer phase. |
| Deep warm reset asserts NAC resets | Device instantiated; sequencer configured to enter deep warm reset phase (trigger via sequencer API or nac_ready_for_enum + phase progression). | Force sequencer into deep warm reset entry action | nac_sys_rst_n, nac_inf_iosfsb_rst_b, nac_pwrgood_rst_b are asserted (lowered) and HAP callbacks fire. | Observe pin levels and HAP callback invocation events. |
| Redundant drive suppression | Device instantiated. Ensure saved state is known (pins deasserted). | Call nac_hif_pcie0_perst_n0.raise() twice without changing other state. | Second raise() produces no remote drive; implementation logs a no-op and saved level remains unchanged. | Observe logs/behavior indicating suppressed action; no duplicate downstream calls. |

Implementation Notes (for Simics Device Model Developers)
--------------------------------------------------------
Key DML source files:
- srv-pm/code/hwrs-gen2/attributes.dml — strap and attribute definitions (is_ioh_with_cnic, sku_feature_*, strap_dmi_mode_override). *Source: srv-pm/code/hwrs-gen2/attributes.dml*
- srv-pm/code/hwrs-gen2/hwrs-straps.dml — strap handling and strap_attr templates. *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml*
- srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml — c_pin_out_nac / c_pin_out / c_pin_out_hap templates and saved-level logic. *Source: srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml*
- srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml — reset_seq_fsm driver, sequencer state machine, and connection points for nac_ready_for_enum PORT. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*
- srv-pm/code/hwrs-gen2/reset-sequencer-pin-cmds.dml — pin-level commands, pre-indication scheduling, and after-handler implementation. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-pin-cmds.dml*

Template dependencies and behavior:
- c_pin_out_nac derives from a generic c_pin_out template and adds NAC-specific guard checks and saved-level bookkeeping. HAP-capable variants use c_pin_out_hap which invoke HAP callbacks on transitions.
- pin_state_notifier provides PORT-level edge detection; its on_change handler is configured to call into reset_seq_fsm (configured via the PORT context).
- strap_attr and strap_attr_u64 templates are used to expose hardware strap/sku values as read-only attributes at model instantiation.

Extension / override points:
- Sequencer timing: change the 0.001 s delay by editing the after() call in reset-sequencer-pin-cmds.dml.
- Add or remove output pins: add CONNECT instances using c_pin_out_nac in the device node and reference them in the sequencer commands.
- Alter gating logic: modify guard checks in c_pin_out_nac template (or override a specific CONNECT instance) to change when pins are driven (for example, use a new attribute is_primary_imh).
- Intercept HAP notifications: install c_pin_out_hap for pins where downstream device notification is required; HAP callbacks can be used by other models to react to asserted resets.

Simulation fidelity / known differences from real hardware:
- The pre-indication → reset fixed 1 ms delay is a model simplification; real hardware electrical behavior may vary.
- Strap values are static attributes set at instantiation; dynamic sampling behavior is not modeled.
- No register-level MMIO interactions are provided for this capability (no register side-effects).
- After-handler cancel semantics are implicit; there is no explicit cancel token modeled — new scheduling re-schedules implicitly.

Platform Integration Notes (for Platform Architects)
---------------------------------------------------
Role in platform:
- Provides centralized IMH/HWRS reset sequencing and CNIC-aware reset routing for NAC/IOH subsystems and PCIe endpoints. It coordinates PCIe PERST# and NAC reset-bus assertions during boot/enumeration and during warm/deep resets.

Required connections:
- Upstream controller (power-management / platform controller) must connect to nac_ready_for_enum PORT and call signal_raise()/signal_lower() to start enumeration sequencing.
- Downstream devices (PCIe endpoints, IOH/NAC chips) must be connected to the various CONNECTs (nac_hif_pcie0_perst_n0, nac_inf_rstbus_rst_b, nac_sn2sfi_rst_n, etc.) to receive reset assertions.
- If downstream models expect notifications, use c_pin_out_hap variants (HAP callbacks) for pins that must notify connected Simics devices on level changes.

Dependencies:
- The behavior is gated by configuration attributes:
  - is_ioh_with_cnic (bool) — required to drive CNIC-specific outputs; set per IMH die instance.
  - strap_dmi_mode_override, sku_feature_dword5/8, lg_spare_tx_en_b_5_0 — influence sequencer branches and lane/tx enable behavior.
- Sequencer interacts with internal reset FSM drivers; ensure reset_seq_fsm is instantiated and wired to nac_ready_for_enum port context.

Configuration parameters:
- Instantiate device with appropriate attributes to model desired variant:
  - is_ioh_with_cnic: true/false
  - strap_dmi_mode_override: value to override sampled DMI mode
  - sku_feature_dword5, sku_feature_dword8, lg_spare_tx_en_b_5_0: SKU/strap bitfields as required
  Source: srv-pm/code/hwrs-gen2/attributes.dml, srv-pm/code/hwrs-gen2/hwrs-straps.dml

Notes on integration testing:
- For platform-level tests that validate enumeration and PCIe behavior, ensure downstream endpoints are sensitive to PERST# transitions and that nac_ready_for_enum is asserted at the correct point in platform bring-up.
- Ensure that CNIC-related pins are not driven when is_ioh_with_cnic == false; verify that the model's guard logic prevents spurious drives.

References
----------
- srv-pm/code/hwrs-gen2/attributes.dml — strap and attribute definitions. *Source: srv-pm/code/hwrs-gen2/attributes.dml*
- srv-pm/code/hwrs-gen2/hwrs-straps.dml — strap handling. *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml*
- srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml — pin templates and saved-level logic. *Source: srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml*
- srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml — sequencer FSM and nac_ready_for_enum port usage. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*
- srv-pm/code/hwrs-gen2/reset-sequencer-pin-cmds.dml — pre-indication scheduling and pin commands. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-pin-cmds.dml*