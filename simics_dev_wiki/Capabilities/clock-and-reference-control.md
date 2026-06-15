[← Device Overview](overview.md)

---

# Capability: clock-and-reference-control (dmr_imh_hwrs_fv)

Overview
--------
This capability models the HWRS (Hardware Reset Sequencer) clock-and-reference control logic within the DMR IMH device (dmr_imh_hwrs_fv). It exposes reference-clock configuration and readiness outputs, drives per-die enable pins, and accepts several external clock-ready / programming handshake inputs used during power-on and reset sequencing.

Scope
- Simulated: register side-effects (write callbacks), output CONNECT signals (driven via c_pin_out/c_pin_out_hap/c_pin_out_nac templates), input PORTs implemented as pin_state_notifier with on_change() observer callbacks, and the reset-sequencer driver (reset_seq_fsm_driver) observing inputs and register writes to advance sequencing phases.
- Stubbed / Not-modeled: exact enumerated FSM state names and internal timing wheels (no explicit event scheduling data provided), detailed electrical behavior of clocks, and any analog/stability modeling of clocks. Some sequencing branching fidelity depends on external reset-sequencer implementation not included in this capability summary.

How It's Simulated
------------------
Simulation is implemented using DML constructs and template-driven patterns:

- Registers and write-side effects:
  - Register write callbacks are implemented via reg-banks-impl.dml and pwrgd-reset-templates.dml. Writes to sb_cr.HWRS_SEQ_CONTROL and sb_cr.HWRS_DRIVE_PINS_PHASE_3_1 invoke write_action code paths that perform side-effects (driving outputs, mirroring fields, calling forwarding helpers).
  - Hard-reset / sticky behavior uses osdml_sticky / hard_reset overrides where configured.

- Output interfaces (CONNECT nodes):
  - Outputs are modeled with Simics CONNECT node templates: c_pin_out, c_pin_out_hap and c_pin_out_nac. These templates provide raise()/lower() semantics and logging under log_group_name = pwrgd_reset.
  - Typical outputs: rclk_config, xxREFCLK_Rdy, nac_ss_qreqn, s3m_early_comm_open, yyDIE_ENABLEx.

- Input interfaces (PORT nodes):
  - Inputs use pin_state_notifier-based PORTs implementing signal_raise()/signal_lower(), persisting level.val and firing on_change() callbacks observed by the reset-sequencer driver.
  - Typical inputs: rclk_ip_ready, s3m_rclk_programming_done, cro_clk_valid, nac_ready_for_enum.

- FSM / Sequencing:
  - The reset sequencing logic is implemented in reset-sequencer driver code (reset-sequencer-fsm.dml) and observes register writes and pin_state_notifier on_change events to transition through sequencing phases (BCLK/REFCLK waits, breakpoints, Phase-4 IP disables).
  - Explicit state labels and timed event scheduling are not provided in the available model description.

Primary source files:
- srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml
- srv-pm/code/hwrs-gen2/reg-banks-impl.dml
- srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml
- srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml
- srv-pm/code/hwrs-gen2/reset-sequencer-pin-cmds.dml
*Source: srv-pm/code/hwrs-gen2/*

Working Flow
------------
High-level operation (state-driven, observer pattern):

- Inputs are edge-signalled via pin_state_notifier:
  - When an external component calls signal_raise()/signal_lower() on an input PORT, the pin_state_notifier updates level.val and fires on_change() observers. The reset_seq_fsm_driver registers observers to these on_change notifications to advance sequencing.
  - Inputs of interest include s3m_rclk_programming_done, cro_clk_valid, rclk_ip_ready, nac_ready_for_enum.

- Register writes drive outputs and can advance the sequencer:
  - Writes to sb_cr.HWRS_SEQ_CONTROL (notably Imh_Disable_Programming_Done and Break_On_Index_Valid fields) perform side-effects: mirror to HWRS_WAIT_PINS_PHASE_3_1, drive yyDIE_ENABLEx outputs per CBB fuse-disable state, apply Phase-4 IP disables (HAMVF/PCIe groups), assert xxREFCLK_Rdy when sequencing conditions are met, and remove sequencer breakpoints when Break_On_Index_Valid is written 1→0.
  - Writes to sb_cr.HWRS_DRIVE_PINS_PHASE_3_1 have write_action only on the Cnic_S0_Pwr_Ok_Int field which calls cnic_s0_pwr_ok_int_forward() on value change, asserting/de-asserting the CNIC S0 power-OK interrupt. Other fields are stored without callbacks.

- Output behavior:
  - Outputs are driven by c_pin_out templates using raise()/lower() semantics. For example, xxREFCLK_Rdy is asserted via the sb_cr.HWRS_SEQ_CONTROL write path when sequencing conditions are met.
  - rclk_config is driven to configure downstream clock-management logic when configured by sequencing code paths.

- Mirror behavior:
  - Imh_Disable_Programming_Done writes are mirrored into HWRS_WAIT_PINS_PHASE_3_1 as part of the write path to maintain a consistent wait-pin representation.

Detailed flows (examples)
- s3m-rclk-programming-complete:
  - Trigger: s3m_rclk_programming_done.signal_raise()
  - Input port updates level.val and calls on_change(true); reset_seq_fsm_driver observer runs and may advance sequencing.

- cro-clock-valid-edge:
  - Trigger: cro_clk_valid.signal_raise()
  - Input port sets level.val=true and broadcast on_change; reset sequencer may advance.

- imh-disable-programming-done:
  - Trigger: write to sb_cr.HWRS_SEQ_CONTROL.Imh_Disable_Programming_Done
  - The write driver mirrors value to HWRS_WAIT_PINS_PHASE_3_1, drives yyDIE_ENABLEx outputs per fuse configuration, applies Phase-4 IP disables, and asserts xxREFCLK_Rdy when the sequencer reaches the BCLK-ready condition.

Register Map
------------
| Register | Bank | Access Type | Reset Value | Write Side-Effect | Read Side-Effect |
|----------|------|-------------|-------------|-------------------|------------------|
| sb_cr.HWRS_DRIVE_PINS_PHASE_3_1 | sb_cr | RW | Not specified in model | Cnic_S0_Pwr_Ok_Int: on write, if value changes, calls cnic_s0_pwr_ok_int_forward() which raises (1) or lowers (0) CNIC S0 power-OK interrupt. Other fields stored with no callbacks. *Source: dmr_imh_b0_hwrs_fv_regs.dml / reg-banks-impl.dml* | Default read returns stored values. osdml_sticky attributes affect hard-reset behavior if present. *Source: reg-banks-impl.dml* |
| sb_cr.HWRS_SEQ_CONTROL | sb_cr | RW | Not specified in model | Writing Imh_Disable_Programming_Done: mirrors value to HWRS_WAIT_PINS_PHASE_3_1, drives yyDIE_ENABLEx per per-CBB fuse-disable state, applies Phase-4 IP disables (HAMVF/PCIe groups), conditionally advances reset-sequencer toward BCLK-ready wait target, asserts xxREFCLK_Rdy CONNECT when conditions met. Writing Break_On_Index_Valid 1→0 removes sequencer breakpoint behavior. *Source: pwrgd-reset-templates.dml / reg-banks-impl.dml* | No special read callbacks documented; reads return stored values. *Source: reg-banks-impl.dml* |

Interface Signals
-----------------
| Signal | Direction | Interface Type | Trigger Condition | Action |
|--------|-----------|----------------|-------------------|--------|
| rclk_config | OUT | c_pin_out | Driven by HWRS sequencing code paths when reference-clock configuration must be communicated | Template raise()/lower() set the CONNECT; logged under pwrgd_reset. *Source: pwrgd-reset-templates.dml* |
| xxREFCLK_Rdy | OUT | c_pin_out | Asserted by sb_cr.HWRS_SEQ_CONTROL write path when sequencing conditions (BCLK/REFCLK milestones) are met | c_pin_out raise() signals downstream that refclk is ready; lower() deasserts. *Source: pwrgd-reset-templates.dml* |
| nac_ss_qreqn | OUT | c_pin_out_nac | Driven when NAC subsystem must block S3M access until early S3M init completes | Active-low QREQn driven via c_pin_out_nac template. *Source: reg-banks-impl.dml* |
| s3m_early_comm_open | OUT | c_pin_out[_hap] | Driven as part of early S3M sequencing (when early communication allowed) | raise()/lower() via template. *Source: reset-sequencer-pin-cmds.dml* |
| yyDIE_ENABLEx | OUT | c_pin_out | Driven by HWRS_SEQ_CONTROL write (Imh_Disable_Programming_Done) per per-CBB fuse-disable state | One or more die-enable outputs are asserted/de-asserted per fuse configuration. *Source: pwrgd-reset-templates.dml / hwrs-cbb-disable.dml* |
| rclk_ip_ready | IN | signal (pin_state_notifier) | External Reference Clock IP signals its output clock stable via signal_raise() | Updates level.val, fires on_change() observers (reset-sequencer). *Source: reg-banks-impl.dml* |
| s3m_rclk_programming_done | IN | signal (pin_state_notifier) | S3M subsystem signals RCLK programming completion via signal_raise() | Updates level.val and immediately invokes attached on_change(true) callbacks (reset_seq_fsm_driver). *Source: reset-sequencer-fsm.dml* |
| cro_clk_valid | IN | signal (pin_state_notifier) | External CRO clock controller asserts when CRO clock is valid via signal_raise() | Guards redundant transitions; sets level.val=true and broadcasts on_change to observers. *Source: reg-banks-impl.dml* |
| nac_ready_for_enum | IN | signal (pin_state_notifier) | NAC subsystem signals readiness for enumeration | level.val update and on_change() to reset sequencer observers. *Source: reset-sequencer-pin-cmds.dml* |

Behavioral Specification (for Software Feature Validators)
---------------------------------------------------------
Testable WHEN -> THEN statements suitable for automated validation:

1. WHEN s3m_rclk_programming_done.signal_raise() is invoked by an external model -> THEN the s3m_rclk_programming_done port level becomes asserted and the reset_seq_fsm_driver on_change(true) observer is invoked (reset sequencing logic is notified). Observable: on_change hook executed; subsequent sequencing actions may write sb_cr registers or drive outputs such as xxREFCLK_Rdy.
   *Source: reset-sequencer-fsm.dml*

2. WHEN cro_clk_valid.signal_raise() is invoked -> THEN cro_clk_valid.level.val becomes true and on_change() observers are called exactly once for the transition (no redundant callbacks if already true). Observable: observer invocation and level readback true.
   *Source: reg-banks-impl.dml*

3. WHEN software writes sb_cr.HWRS_SEQ_CONTROL.Imh_Disable_Programming_Done = 1 (or toggles the field) -> THEN:
   - The written value is mirrored into sb_cr.HWRS_WAIT_PINS_PHASE_3_1.
   - yyDIE_ENABLEx outputs are driven consistent with per-CBB fuse-disable state.
   - Phase-4 IP disables are applied for HAMVF/PCIe groups.
   - If sequencing conditions are met, xxREFCLK_Rdy CONNECT is asserted.
   Observable: readback of HWRS_WAIT_PINS_PHASE_3_1, inspection of yyDIE_ENABLEx CONNECT signal states, and xxREFCLK_Rdy asserted.
   *Source: pwrgd-reset-templates.dml*

4. WHEN breaking behavior is removed by writing sb_cr.HWRS_SEQ_CONTROL.Break_On_Index_Valid from 1→0 -> THEN the sequencer breakpoint behavior is removed and the reset-sequencer may advance further (no breakpoint stop). Observable: no breakpoint-induced stalls in sequencing and possible assertion of outputs that follow sequential advancement.
   *Source: pwrgd-reset-templates.dml*

5. WHEN software writes sb_cr.HWRS_DRIVE_PINS_PHASE_3_1.Cnic_S0_Pwr_Ok_Int = 1 (value change) -> THEN cnic_s0_pwr_ok_int_forward() is called and the CNIC S0 power-OK interrupt is asserted (raised). Conversely, writing 0 de-asserts it. Observable: CNIC S0 interrupt state and any interrupt consumers receive the corresponding edge.
   *Source: dmr_imh_b0_hwrs_fv_regs.dml / reg-banks-impl.dml*

Test Case Scenarios (for Software Feature Validators)
----------------------------------------------------
| Scenario | Setup | Action | Expected Result | Verification Point |
|----------|-------|--------|-----------------|--------------------|
| S3M RCLK Programming Completion | Device boot with reset-sequencer attached and s3m_rclk_programming_done observer registered | Call s3m_rclk_programming_done.signal_raise() | reset_seq_fsm_driver on_change invoked; sequencer becomes eligible to progress; subsequent register writes may occur | Verify on_change callback hit (via HAP/log) and check for expected register writes or xxREFCLK_Rdy assertion |
| CRO Clock Valid Edge | CRO model connected to cro_clk_valid PORT | cro_clk_valid.signal_raise() | cro_clk_valid.level.val == true and reset-sequencer observers invoked once | Read level via debug API and assert observer callback count |
| IMH Disable Programming Done Write | Per-CBB fuse values configured; initial yyDIE_ENABLEx deasserted | Write Imh_Disable_Programming_Done=1 to sb_cr.HWRS_SEQ_CONTROL | HWRS_WAIT_PINS_PHASE_3_1 mirrored; yyDIE_ENABLEx driven according to fuses; Phase-4 IP disables applied; xxREFCLK_Rdy asserted if sequencing conditions satisfied | Read HWRS_WAIT_PINS_PHASE_3_1, sample yyDIE_ENABLEx CONNECTs, check xxREFCLK_Rdy CONNECT asserted |
| CNIC S0 Pwr OK Interrupt Forwarding | CNIC interrupt consumer connected | Write Cnic_S0_Pwr_Ok_Int = 1 then = 0 to sb_cr.HWRS_DRIVE_PINS_PHASE_3_1 | On 1: CNIC S0 interrupt asserted; On 0: CNIC S0 interrupt deasserted | Observe CNIC interrupt line via CONNECT or interrupt logging |
| Breakpoint Removal Advances Sequencer | Reset-sequencer paused due to Break_On_Index_Valid==1 breakpoint | Write Break_On_Index_Valid = 0 to sb_cr.HWRS_SEQ_CONTROL | Breakpoint behavior removed; sequencer advances and may assert outputs like xxREFCLK_Rdy | Verify breakpoint removal via sequencer status (logs/HAP) and subsequent output assertions |

Implementation Notes (for Simics Device Model Developers)
---------------------------------------------------------
Key DML source files:
- Register definitions: srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml
- Register write implementations & helpers: srv-pm/code/hwrs-gen2/reg-banks-impl.dml
- Power-good / reset templates and write-action orchestrations: srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml
- Reset sequencer FSM and observers: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml
- Pin/command helpers: srv-pm/code/hwrs-gen2/reset-sequencer-pin-cmds.dml
- CBB/fuse disable handling: srv-pm/code/hwrs-gen2/hwrs-cbb-disable.dml
*Source: Code map above*

Template dependencies and inheritance:
- Outputs use c_pin_out / c_pin_out_hap / c_pin_out_nac templates. These templates provide:
  - raise()/lower() methods
  - logging grouping (log_group_name = pwrgd_reset)
  - null-object guards and HAP callbacks where appropriate
- Inputs use pin_state_notifier template which implements signal_raise()/signal_lower(), persistent level.val, and on_change() notification semantics.
- Reset-sequencer driver uses observer pattern: it registers on_change callbacks to pin_state_notifier instances and also coordinates with register write callbacks (write_action paths).
*Source: pwrgd-reset-templates.dml, reg-banks-impl.dml*

Extension / override points:
- Add or modify write_action code associated with sb_cr register fields in the device's regs.dml to change write-time side-effects.
- Extend c_pin_out templates (or wrap their instances) to add additional logging, HAPs, or conditional guards.
- The reset-sequencer FSM is implemented in reset-sequencer-fsm.dml — to change sequencing behavior, modify or extend this DML FSM, or register additional observers in reset-sequencer-pin-cmds.dml.
- For adding new inputs/outputs, add PORT/CONNECT node entries in the regs DML and implement corresponding pin command helpers in reset-sequencer-pin-cmds.dml.
*Source: reset-sequencer-fsm.dml, reset-sequencer-pin-cmds.dml*

Simulation fidelity / known differences from real hardware:
- FSM state enumerations and explicit timed event scheduling are not exposed; tests should observe high-level sequencing behavior rather than rely on precise internal state names.
- The model relies on external components (reference clock IP, CRO, S3M controller) to signal readiness; the HWRS does not model clock stabilization times or jitter.
- Some behaviors are gated by configuration straps or fuses (e.g., per-CBB disable state, fxr_disable_strap) which are simulated as static configuration attributes rather than dynamic fuse blowing.
- Event scheduling details (delays, timeouts) are not supplied in the analyzed context; where timing matters, tests must drive inputs and observe outcomes rather than rely on implicit timeouts.
*Source: summarized from provided capability analysis*

Platform Integration Notes (for Platform Architects)
---------------------------------------------------
Role in platform:
- The HWRS clock-and-reference-control capability is the central orchestration point in the IMH for enabling dies, gating subsystem access (NAC/S3M), and indicating reference clock readiness to downstream consumers during platform power-on and reset sequencing.

Required signal connections and counterparts:
- Inputs (PORTs) to connect to:
  - rclk_ip_ready <- Reference Clock IP block (signals reference clock stable)
  - s3m_rclk_programming_done <- S3M clock-programming controller
  - cro_clk_valid <- CRO clock controller
  - nac_ready_for_enum <- NAC subsystem
- Outputs (CONNECTs) to connect to:
  - xxREFCLK_Rdy -> downstream consumers waiting for refclk stability
  - rclk_config -> clock-management components (to configure RCLK)
  - nac_ss_qreqn -> NAC subsystem (block/unblock S3M access)
  - s3m_early_comm_open -> S3M subsystem early communication gate
  - yyDIE_ENABLEx -> per-die enable pins to die power logic
*Source: Interface Output/Input sections and code map*

Dependencies on other device capabilities / services:
- Reset-sequencer driver (reset-sequencer-fsm.dml) — the HWRS outputs and register write side-effects are coordinated by this driver.
- CBB/fuse disable handling logic (hwrs-cbb-disable.dml) — drives per-CBB logic for yyDIE_ENABLEx.
- Phase-4 IP disable logic (hwrs-ip-disable.dml) — used when Imh_Disable_Programming_Done is written.
- External clock sources and controllers to drive input PORTs for sequencing events.
*Source: Code map references*

Configuration parameters:
- fxr_disable_strap: a saved attribute (uint64_attr) provided at device instantiation; when set indicates FXR sequencing should be bypassed (semantic equivalent to skip_fffc, skip_FIVR, skip_PCU_PLL fuses). Sequencing logic reads this strap to decide whether to bypass FXR-specific flows.
  *Source: hwrs-straps.dml*

References
----------
- Device register definitions: srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml *Source: code map*
- Register write handlers and template orchestration: srv-pm/code/hwrs-gen2/reg-banks-impl.dml, srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml *Source: code map*
- Reset sequencer FSM and pin commands: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml, srv-pm/code/hwrs-gen2/reset-sequencer-pin-cmds.dml *Source: code map*
- Strap and CBB/IP disable helpers: srv-pm/code/hwrs-gen2/hwrs-straps.dml, srv-pm/code/hwrs-gen2/hwrs-cbb-disable.dml, srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml *Source: code map*

If you want, I can:
- Produce concrete Simics Python/CLI test scripts that exercise the Behavioral Specification cases.
- Extract or draft the specific DML write_action snippets for sb_cr.HWRS_SEQ_CONTROL and sb_cr.HWRS_DRIVE_PINS_PHASE_3_1 to serve as editable templates.