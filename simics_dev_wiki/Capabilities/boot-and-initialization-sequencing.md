[← Device Overview](overview.md)

---

# boot-and-initialization-sequencing

Overview
- This capability models the HWRS Gen2 IMH (dmr_imh_hwrs_fv) boot-and-initialization sequencing logic used for early-boot coordination, IP-disable resolution and driving early power/reset outputs during platform bring-up.
- Primary role: implement the HWRS reset sequencer FSM, accept early-boot signals from upstream firmware/units, apply fuse/strap-derived IP-disable masks, and drive downstream power/reset/boot-done pins so other components can progress their bring-up.
- Scope (what is simulated vs. stubbed):
  - Simulated: register semantics (including resolved IP-disable reads), write side-effects from HWRS_SEQ_CONTROL (per-die enables, mirror fields, Phase‑4 IP disables, xxREFCLK_Rdy assertion), reset sequencer FSM progression on input signals and register writes, saved attributes representing sampled straps and fuse words, and pin-level outputs via c_pin_out/c_pin_out_hap.
  - Stubbed / simplified: low-level electrical/timing behavior, detailed delay modeling and real-time scheduling of analog transitions, and any HW-internal microsequencer timing that is not expressed in the FSM callbacks. Event scheduling/timers are not provided by the model (no scheduled event queue entries are used for fine-grained hardware delays). *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml; srv-pm/code/hwrs-gen2/attributes.dml*

How It's Simulated
- DML constructs used:
  - Registers: sb_cr register bank nodes implement read/write callbacks. The read_register override for sb_cr.IP_DISABLE_RESOLVED_CR_DWORD1 returns the bitwise OR of the software control register and the fuse word. Writes to sb_cr.HWRS_SEQ_CONTROL are handled by a write callback which implements mirrors, per-die output driving and sequencer interaction. *Source: srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml*
  - Saved/config attributes: sampled straps and fuses are modeled with uint64_attr, bool_attr and strap_attr_u64 (examples: strap_fw_agent, procdis_n, disable_core_start, ip_disable_fuses_dword4/6, max_cbb_num_per_imh, is_primary_imh). These attributes are read by initialization logic and by the ip-disable resolution path. *Source: srv-pm/code/hwrs-gen2/attributes.dml; srv-pm/code/hwrs-gen2/hwrs-straps.dml*
  - FSM driver: reset_seq_fsm_driver implements a reset sequencing FSM and exposes on_change callbacks used to advance the sequencer when inputs or register writes change state. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*
  - Pin/Signal interface: pin_state_notifier ports implement inputs (signal_raise/signal_lower) and c_pin_out / c_pin_out_hap are used for outputs. Input signal changes update internal stored levels and invoke on_change handlers; outputs are driven via c_pin_out on_change callbacks. *Source: srv-pm/code/hwrs-gen2/pwrgd-reset-pins.dml; srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml*
  - IP-disable logic: separate DML templates implement grouping and masking for Phase‑4 disables and CBB-level disable logic. *Source: srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml; srv-pm/code/hwrs-gen2/hwrs-cbb-disable.dml*
- What is not modelled in detail:
  - Transient electrical timing, analog domain interactions and microsecond/microsecond-accurate delay chains. The model advances the logical FSM immediately on relevant stimuli rather than modeling real hardware latencies. *Source: Event Scheduling (not available) and reset-sequencer-fsm.dml*

Working Flow
- State machine and major flows:
  - early-boot-complete-sequencing
    - Trigger: an input pin_state_notifier signal_raise (e.g. fusectrl_early_boot_done, s0_early_boot_done).
    - Flow: the port sets the stored level, calls notify_level_change/on_change; reset_seq_fsm_driver.on_change(true) gets invoked; FSM advances toward its target state; as state advances, outputs such as s3m_rclk_boot_done and s3m_early_comm_open are asserted via c_pin_out/c_pin_out_hap callbacks. Result: downstream CONNECT pins asserted and platform sequencer state advanced. *Source: capability flows and reset-sequencer-fsm.dml*
  - resolved-ip-disable-read
    - Trigger: SW reads sb_cr.IP_DISABLE_RESOLVED_CR_DWORD1.
    - Flow: the read_register override returns cr_reg.val | fuses_reg.val (bitwise OR). Result: software sees the resolved IP-disable mask (software CR OR hardware fuses). *Source: dmr_imh_b0_hwrs_fv_regs.dml*
  - sequencer-control-register-write
    - Trigger: SW writes sb_cr.HWRS_SEQ_CONTROL.
    - Flow: write callback updates fields (Imh_Disable_Programming_Done, mirror fields), mirrors values into HWRS_WAIT_PINS_PHASE_3_1, applies Phase‑4 IP-disable masks (HAMVF/PCIe groups), drives per-die yyDIE_ENABLEx outputs subject to CBB fuse-disable state, may assert xxREFCLK_Rdy and may advance the reset sequencer (or clear Break_On_Index_Valid breakpoints). Result: outputs driven, masks applied, and FSM progress triggered. *Source: dmr_imh_b0_hwrs_fv_regs.dml; srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml*
- Registers involved and semantics:
  - sb_cr.IP_DISABLE_RESOLVED_CR_DWORD1 (RO) — read override: return software CR OR fuse word. Writes are no-ops. *Source: dmr_imh_b0_hwrs_fv_regs.dml*
  - sb_cr.HWRS_SEQ_CONTROL (RW) — write callback with side-effects (mirrors, per-die pins, Phase‑4 disables, xxREFCLK_Rdy assertion, sequencer advance). *Source: dmr_imh_b0_hwrs_fv_regs.dml*
- Interface signals (PORT / CONNECT) and conditions:
  - Inputs (examples): early_boot_debug_exit, bpk_early_boot_done, s0_early_boot_done, fusectrl_early_boot_done, nac_fw_loader_done, s5_early_boot_done. Each is a pin_state_notifier; signal_raise/ signal_lower set stored level and call on_change handlers that invoke reset_seq_fsm_driver.on_change. *Source: capability data; pwrgd-reset-pins.dml*
  - Outputs (examples): vnn_early_boot_done_to_s3, s3m_rclk_boot_done, s3m_early_comm_open, early_boot_pwrgood_rst_b, yyDIE_ENABLEx, HWRS_WAIT_PINS_PHASE_3_1, xxREFCLK_Rdy. These are implemented with c_pin_out/c_pin_out_hap callbacks and driven when internal conditions or the FSM transitions indicate they should be asserted/deasserted. *Source: pwrgd-reset-templates.dml; dmr_imh_b0_hwrs_fv_regs.dml*
- Event scheduling:
  - The model does not schedule hardware-timed events beyond immediate callback-driven FSM transitions. No explicit timers are used in the model as described. (Event Scheduling: not available).

Register Map

| Register                                 | Bank  | Access Type | Reset Value                    | Write Side-Effect                                                                                                                                                                           | Read Side-Effect                                                                                      |
|-----------------------------------------:|:-----:|:-----------:|:------------------------------:|:--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------:|:-----------------------------------------------------------------------------------------------------:|
| sb_cr.IP_DISABLE_RESOLVED_CR_DWORD1     | sb_cr | RO          | not specified (model-dependent) | writes are silenced / no-op (read-only).                                                                                                                                                   | read_register override returns cr_reg.val | fuses_reg.val (bitwise OR) — resolves software CR with fuse word. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |
| sb_cr.HWRS_SEQ_CONTROL                   | sb_cr | RW          | not specified (model-dependent) | write callback updates Imh_Disable_Programming_Done, mirrors into HWRS_WAIT_PINS_PHASE_3_1, applies Phase‑4 IP-disable masks (HAMVF/PCIe groups), drives yyDIE_ENABLEx subject to CBB fuse state, may assert xxREFCLK_Rdy, may advance/reset sequencer and clear Break_On_Index_Valid breakpoint. *Source: dmr_imh_b0_hwrs_fv_regs.dml* | No special read-side effects documented in model. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |

Interface Signals

| Signal                          | Direction | Interface Type       | Trigger Condition                                 | Action / Driven By |
|--------------------------------:|:---------:|:--------------------:|:--------------------------------------------------|:-------------------|
| early_boot_debug_exit           | IN        | pin_state_notifier   | external controller calls signal_raise/ lower     | set stored level, notify_level_change, invoke on_change -> reset sequencer. *Source: capability data* |
| bpk_early_boot_done             | IN        | pin_state_notifier   | BPK asserts/deasserts early-boot-done line        | update stored level, broadcast state, invoke reset sequencer on_change. *Source: capability data* |
| s0_early_boot_done              | IN        | pin_state_notifier   | S3M firmware signals S0 early-boot complete       | on raise invoke reset_seq_fsm_driver.on_change -> sequencer advances. *Source: capability data* |
| fusectrl_early_boot_done        | IN        | pin_state_notifier   | Fuse controller signals early-boot-complete       | set stored level and invoke sequencer on_change. *Source: capability data* |
| s5_early_boot_done              | IN        | pin_state_notifier   | S5 domain early-boot line                         | similar handling to other early-boot inputs. *Source: capability data* |
| vnn_early_boot_done_to_s3       | OUT       | c_pin_out            | internal VNN early-boot completion conditions met | driven via c_pin_out/c_pin_out_hap on_change; connected to S3 power-state component. *Source: pwrgd-reset-templates.dml* |
| s3m_rclk_boot_done              | OUT       | c_pin_out / c_pin_out_hap | model boot-done condition for S3M ref clock      | c_pin_out on_change updates stored s3m_rclk_boot_done_level; used by power-sequencing logic and reset ordering. *Source: pwrgd-reset-pins.dml* |
| s3m_early_comm_open             | OUT       | c_pin_out            | early-comm-open condition held                    | driven via c_pin_out when FSM/state indicates. *Source: capability data* |
| early_boot_pwrgood_rst_b        | OUT       | c_pin_out            | (model-dependent)                                 | driven via c_pin_out; used for power-good/reset domain. *Source: capability data (truncated list)* |
| yyDIE_ENABLEx (per-die outputs) | OUT       | c_pin_out            | HWRS_SEQ_CONTROL Imh_Disable_Programming_Done write and fuse state | driven per-die subject to CBB fuse disables; controlled by HWRS_SEQ_CONTROL write. *Source: dmr_imh_b0_hwrs_fv_regs.dml; hwrs-cbb-disable.dml* |
| HWRS_WAIT_PINS_PHASE_3_1        | OUT       | c_pin_out            | mirrored from HWRS_SEQ_CONTROL                    | mirror behavior implemented on write to HWRS_SEQ_CONTROL. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |
| xxREFCLK_Rdy                    | OUT       | c_pin_out            | asserted by HWRS_SEQ_CONTROL write under conditions | asserted by write callback; serves as BCLK-ready indication. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |

Behavioral Specification (for Software Feature Validators)
- WHEN software reads sb_cr.IP_DISABLE_RESOLVED_CR_DWORD1 -> THEN the returned 32/64-bit value equals (software_CR_value OR ip_disable_fuses_value) where ip_disable_fuses_value is the model's ip_disable_fuses_* saved attribute. Observable: SW-visible register read equals bitwise OR of the two sources. *Source: dmr_imh_b0_hwrs_fv_regs.dml*
- WHEN an input early-boot pin_state_notifier (e.g., s0_early_boot_done or fusectrl_early_boot_done) issues signal_raise -> THEN reset_seq_fsm_driver.on_change(true) is invoked and the HWRS reset sequencer FSM advances toward its configured target state; subsequent FSM-driven outputs (e.g., s3m_rclk_boot_done, s3m_early_comm_open) will be asserted when the FSM reaches the corresponding state. Observable: change in c_pin_out pins and sequencer state progression. *Source: capability flows; reset-sequencer-fsm.dml*
- WHEN software writes HWRS_SEQ_CONTROL with Imh_Disable_Programming_Done asserted -> THEN per-die yyDIE_ENABLEx outputs are driven (subject to CBB fuse-disable state) and HWRS_WAIT_PINS_PHASE_3_1 mirrors are updated; xxREFCLK_Rdy may be asserted and the reset sequencer may be advanced toward a BCLK-ready wait target. Observable: change on per-die outputs, HWRS_WAIT_PINS_PHASE_3_1, and xxREFCLK_Rdy pins. *Source: dmr_imh_b0_hwrs_fv_regs.dml; hwrs-cbb-disable.dml*
- WHEN software writes Break_On_Index_Valid field in HWRS_SEQ_CONTROL from 1 -> 0 while the sequencer is at a breakpoint -> THEN the write clears the active sequencer breakpoint and allows (or triggers deferred) FSM progression as defined by the sequencer semantics. Observable: sequencer breakpoint cleared and FSM state advances. *Source: dmr_imh_b0_hwrs_fv_regs.dml*
- WHEN the model drives s3m_rclk_boot_done (via c_pin_out on_change) -> THEN the internal saved attribute s3m_rclk_boot_done_level is updated and power-sequencing logic that reads this attribute will observe the change. Observable: s3m_rclk_boot_done remote pin level and saved attribute value in checkpoint/state. *Source: capability data; pwrgd-reset-pins.dml*

Test Case Scenarios (for Software Feature Validators)

1) Resolved IP-disable read
- Setup: Configure device attributes ip_disable_fuses_dword6 (or dword4) to 0x0000_000F and write the software IP_DISABLE_CR (control register) to 0x0000_00F0.
- Action: From target software, read sb_cr.IP_DISABLE_RESOLVED_CR_DWORD1.
- Expected Result: read value == 0x0000_00FF (bitwise OR).
- Verification Point: Check Simics register read return matches expected OR result; check that the device's fuses attribute holds the configured fuse word. *Source: dmr_imh_b0_hwrs_fv_regs.dml*

2) Sequencer advances on s0_early_boot_done
- Setup: Ensure HWRS sequencer is at a state waiting for S0 early-boot; connect and enable s0_early_boot_done input.
- Action: Driver/other device invokes signal_raise() on s0_early_boot_done.
- Expected Result: reset_seq_fsm_driver.on_change called; sequencer state transitions to next state; s3m_early_comm_open and/or s3m_rclk_boot_done asserted according to FSM target.
- Verification Point: Observe pin levels for s3m_early_comm_open and s3m_rclk_boot_done in Simics and record sequencer state transition events (via DML HAPs/logging). *Source: capability flows; reset-sequencer-fsm.dml*

3) HWRS_SEQ_CONTROL write drives per-die enables and xxREFCLK_Rdy
- Setup: Program CBB fuse attributes to enable/disable certain dice (using hwrs-cbb-disable template), ensure yyDIE_ENABLEx outputs are unasserted initially.
- Action: Software writes Imh_Disable_Programming_Done=1 (and optionally sets Phase‑4 group-disable bits) into sb_cr.HWRS_SEQ_CONTROL.
- Expected Result: yyDIE_ENABLEx pins asserted/cleared per CBB fuse state and write fields; HWRS_WAIT_PINS_PHASE_3_1 mirrors reflect the written values; xxREFCLK_Rdy asserted if the write semantics require it.
- Verification Point: Inspect per-die pin states, HWRS_WAIT_PINS_PHASE_3_1 mirror register fields, and xxREFCLK_Rdy pin state in Simics. *Source: dmr_imh_b0_hwrs_fv_regs.dml; hwrs-cbb-disable.dml*

4) Breakpoint clear behavior on Break_On_Index_Valid
- Setup: Place sequencer into breakpoint (Break_On_Index_Valid==1 and sequencer paused).
- Action: Software writes Break_On_Index_Valid = 0 in sb_cr.HWRS_SEQ_CONTROL.
- Expected Result: active breakpoint is cleared and sequencer resumes (subject to any deferred semantics); FSM moves forward per sequencer definition.
- Verification Point: Validate sequencer breakpoint event cleared, FSM state advanced, and corresponding output pin transitions. *Source: dmr_imh_b0_hwrs_fv_regs.dml; reset-sequencer-fsm.dml*

5) VNN early-boot done output assertion
- Setup: FSM configured so that when a set of early-boot inputs are asserted, VNN early-boot done should assert; ensure those inputs are unasserted initially.
- Action: Assert the required combination of inputs (e.g., fusectrl_early_boot_done then s0_early_boot_done) to cause sequencer to reach that state.
- Expected Result: vnn_early_boot_done_to_s3 c_pin_out asserted.
- Verification Point: Monitor vnn_early_boot_done_to_s3 pin in Simics and validate the saved state that produced the assertion. *Source: capability flows; pwrgd-reset-templates.dml*

Implementation Notes (for Simics Device Model Developers)
- Key DML source files (implementation map):
  - Device register definitions and read/write handlers: srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml. *Source: code map*
  - Reset sequencer FSM and driver: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml. *Source: code map*
  - IP-disable group logic and masks: srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml. *Source: code map*
  - CBB disable logic: srv-pm/code/hwrs-gen2/hwrs-cbb-disable.dml. *Source: code map*
  - Pin and pwrgd-reset templates: srv-pm/code/hwrs-gen2/pwrgd-reset-pins.dml, srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml. *Source: code map*
  - Register banks and generic register template implementations: srv-pm/code/hwrs-gen2/reg-banks-impl.dml. *Source: code map*
  - Attributes and strap definitions: srv-pm/code/hwrs-gen2/attributes.dml, srv-pm/code/hwrs-gen2/hwrs-straps.dml. *Source: code map*
  - Resetbus / interconnect templates: srv-pm/code/hwrs-gen2/resetbus.dml. *Source: code map*
- Template dependencies and inheritance:
  - The device composes/regenerates behaviour from reg-banks-impl templates, pwrgd-reset templates and FSM template(s). Register read/write overrides are provided at the sb_cr.* nodes in the device-specific regs DML. *Source: reg-banks-impl.dml; pwrgd-reset-templates.dml*
- Extension and override points:
  - Register handlers: override read_register for sb_cr.IP_DISABLE_RESOLVED_CR_DWORD1; add write callbacks/after_write handlers for sb_cr.HWRS_SEQ_CONTROL to modify mirror/masked behavior.
  - FSM hooks: reset_seq_fsm_driver.on_change() is the canonical entrypoint; extensions can add additional conditions or new states in reset-sequencer-fsm.dml.
  - Ports and pins: new pin_state_notifier inputs or c_pin_out outputs can be declared and wired; adapt c_pin_out_hap callbacks to add diagnostic logging or different guard logic.
  - Attributes: add/modify saved uint64_attr/strap_attr_u64 attributes for additional fuse or strap fields; these are read at init and used by the IP-disable path. *Source: attributes.dml*
- Simulation fidelity notes and known differences from real HW:
  - Fuse/strap behavior is modeled as configuration attributes sampled at instantiation. There is no on-chip fuse blow or dynamic physical fuse behavior modeled (fuse changes require reconfiguration). *Source: attributes.dml*
  - Timing is logical and driven by callbacks: sequencer progression is triggered on input or register writes and does not model internal analog/temporal delays in hardware. There are no scheduled hardware timers for fine-grained delays. *Source: Event Scheduling (not available); reset-sequencer-fsm.dml*
  - Resolved IP-disable is implemented as a simple bitwise OR of software CR and fuse word (functional equivalence but not necessarily the same probe points or hardware read paths). *Source: dmr_imh_b0_hwrs_fv_regs.dml*
  - Breakpoint semantics are implemented but may be simplified (deferred semantics and micro-conditions should be validated against real HW if timing-sensitive behavior is required). *Source: dmr_imh_b0_hwrs_fv_regs.dml*

Platform Integration Notes (for Platform Architects)
- Role in platform:
  - Acts as an IMH-local HWRS which coordinates early-boot handshake between firmware layers (S3M, BPK, NAC), applies hardware-disabling masks, and issues platform-level early-boot-ready signals used by power controllers and downstream devices to continue bring-up.
- Required PORT/CONNECT signal connections and expected counterparts:
  - Inputs (connect from): S3M firmware / S3M early-boot; BPK (boot part keeper); fuse controller; NAC/FW loader; external debug/boot controllers. These must provide signal_raise/signal_lower semantics (pin_state_notifier). *Source: capability data*
  - Outputs (connect to): S3 power-state components and power/reset controllers (vnn_early_boot_done_to_s3, s3m_rclk_boot_done, s3m_early_comm_open, early_boot_pwrgood_rst_b), per-die CBB power controllers or die-enablers (yyDIE_ENABLEx), and resetbus/wait pins (HWRS_WAIT_PINS_PHASE_3_1, xxREFCLK_Rdy). *Source: pwrgd-reset-templates.dml; dmr_imh_b0_hwrs_fv_regs.dml*
- Dependencies on other device capabilities/platform services:
  - Fuse/strap provisioning: relies on attributes that must be configured per platform instantiation (ip_disable_fuses_dword4/6, procdis_n, strap_safe_mode_boot, disable_core_start, max_cbb_num_per_imh, is_primary_imh, strap_fw_agent). *Source: attributes.dml; hwrs-straps.dml*
  - Register bank infrastructure: depends on the reg-banks-impl templates for correct read/write interception and HAP registration. *Source: reg-banks-impl.dml*
  - Reset sequencing consumers: other devices must inspect the driven pins (CONNECT endpoints) and respond to them as the model does not perform downstream device startup actions itself. Architects must wire those downstream devices to these outputs. *Source: pwrgd-reset-pins.dml*
- Configuration parameters that affect behavior:
  - strap_safe_mode_boot (uint64_attr): selects safe/recovery boot mode. *Source: attributes.dml*
  - procdis_n (uint64_attr): active-low processor-disable strap. *Source: attributes.dml*
  - disable_core_start (bool_attr): prevents cores from starting. *Source: attributes.dml*
  - ip_disable_fuses_dword4, ip_disable_fuses_dword6 (uint64_attr): fuse words used during resolved IP-disable reads and Phase‑4 masking. *Source: attributes.dml*
  - max_cbb_num_per_imh, is_primary_imh, strap_fw_agent (strap_attr_u64 / uint64_attr): platform layout and firmware-agent behavior. *Source: attributes.dml; hwrs-straps.dml*

References
- DML implementation files (primary): srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml; srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml; srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml; srv-pm/code/hwrs-gen2/attributes.dml; srv-pm/code/hwrs-gen2/pwrgd-reset-pins.dml; srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml; srv-pm/code/hwrs-gen2/hwrs-cbb-disable.dml; srv-pm/code/hwrs-gen2/reg-banks-impl.dml. *Source: Code Map in capability analysis data.*

(End of page)