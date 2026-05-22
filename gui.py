#!/usr/bin/env python3
"""
CPU Pipeline Simulator — CustomTkinter GUI
GUC CSEN601 — Package 1: Spicy Von Neumann Fillet
Drop this file in the ca/ folder (next to src/).
Run: python3 gui_ctk.py
Requires: pip install customtkinter
"""

import customtkinter as ctk
import subprocess, os, sys, re, tempfile, threading, time
from tkinter import filedialog, messagebox

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE   = os.path.dirname(os.path.abspath(__file__))
SRC    = os.path.join(BASE, "src")
BIN    = os.path.join(SRC,  "processor.exe")
BIN_ALT = os.path.join(SRC, "processor_sim")
PROG   = os.path.join(SRC,  "program.txt")

# ─── Theme ────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

NVIDIA   = "#76b900"
NVIDIA_D = "#1a2d00"
BG0      = "#0d1117"
BG1      = "#161b22"
BG2      = "#1e2530"
BG3      = "#252d3a"
BORDER   = "#30363d"
TEXT     = "#e6edf3"
TEXT2    = "#8b949e"
GREEN    = "#3fb950"
CYAN     = "#39d3c4"
BLUE     = "#58a6ff"
AMBER    = "#d29922"
RED      = "#f85149"
PURPLE   = "#bc8cff"

STAGE_COLORS = {
    "IF":  ("#0d2818", "#3fb950"),
    "ID":  ("#0d1f38", "#58a6ff"),
    "EX":  ("#1a0d38", "#bc8cff"),
    "MEM": ("#0d2a2a", "#39d3c4"),
    "WB":  ("#2a1f00", "#d29922"),
}

OPNAMES = {0:"ADD",1:"SUB",2:"MULI",3:"ADDI",4:"BNE",5:"ANDI",6:"XORI",7:"J",8:"SLL",9:"SRL",10:"LW",11:"SW"}

DEFAULT_PROGRAM = """\
# Test Phase 1: Basic ALU and R0 Immortality
ADDI R1 R0 5
ADDI R2 R0 10
ADD R1 R2 R3
ADDI R0 R3 99

# Test Phase 2: Memory Access (Structural Hazard Test)
ADDI R4 R0 1024
SW R3 R4 0
LW R5 R4 0

# Test Phase 3: Control Hazard (Branching)
BNE R1 R2 2
ADD R1 R2 R6
ADD R1 R2 R7
ADDI R8 R0 99
"""

# ─── Simulation back-end (same logic as gui.py) ────────────────────────────────
def compile_binary():
    out = BIN if os.name == "nt" else BIN_ALT
    r = subprocess.run(
        ["gcc", "-O0", "-o", out,
         os.path.join(SRC,"cpu.c"), os.path.join(SRC,"parser.c"), os.path.join(SRC,"main.c"),
         "-I", SRC],
        capture_output=True, text=True)
    return r.returncode == 0, r.stderr.strip(), out

def run_simulation(prog_text, binary=None):
    """Run the simulator; program.txt already matches prog_text."""
    exe = binary or (BIN if os.path.isfile(BIN) else BIN_ALT)
    with open(PROG, "w", encoding="utf-8") as f:
        f.write(prog_text)
    r = subprocess.run([exe], capture_output=True, text=True, cwd=SRC, timeout=10)
    return r.stdout.splitlines(), r.stderr

def parse_output(lines):
    cycles, cur, log = [], None, []
    parsed_insts, final_regs, final_mem = [], {}, {}
    final_pc = 0
    total_cycles = 0
    in_final = False

    cycle_re  = re.compile(r"(?:Cycle (\d+) Summary:|=+ Clock Cycle (\d+) =+)")
    stage_re  = re.compile(r"(IF|ID|EX|MEM|WB)\s*(?:Stage)?:\s*(.+)")
    reg_re    = re.compile(r"Registers -> (.+)")
    wb_re     = re.compile(r"Register update \(WB stage\): R(\d+) = (-?\d+)")
    ml_re     = re.compile(r"Memory update \(MEM stage\): Data Memory \[(\d+)\] = (-?\d+) \(load")
    ms_re     = re.compile(r"Memory update \(MEM stage\): Data Memory \[(\d+)\] = (-?\d+) \(store")
    br_re     = re.compile(r"EX stage output: branch taken, new PC = (\d+)", re.I)
    jmp_re    = re.compile(r"EX stage output: jump taken, new PC = (\d+)", re.I)
    flush_re  = re.compile(r"pipeline flush", re.I)
    total_re  = re.compile(r"Total Clock Cycles: (\d+)")
    freg_re   = re.compile(r"^R(\d+): (-?\d+)$")
    fpc_re    = re.compile(r"^PC: (-?\d+)$")
    fmem_re   = re.compile(r"(Instruction|Data) Memory\s*\[(\d+)\]:\s*(.+)")
    parse_re  = re.compile(r"Loaded Memory\[(\d+)\]: (\S+) -> (0x[0-9A-Fa-f]+)")

    for raw in lines:
        line = raw.strip()
        m = parse_re.match(line)
        if m:
            parsed_insts.append({"addr":int(m.group(1)),"mnem":m.group(2),"hex":m.group(3)})
            log.append(("parse", line)); continue
        m = cycle_re.search(line)
        if m:
            if cur: cycles.append(cur)
            cnum = m.group(1) if m.group(1) else m.group(2)
            cur = {"cycle":int(cnum),"stages":{},"regs":{},"events":[]}
            log.append(("cycle", line)); continue
        m = stage_re.match(line)
        if m and cur:
            cur["stages"][m.group(1)] = m.group(2).strip(); continue
        m = reg_re.match(line)
        if m and cur:
            for p in m.group(1).split("|"):
                kv = p.strip().split(":")
                if len(kv)==2: cur["regs"][kv[0].strip()] = kv[1].strip()
            continue
        matched = False
        for pat, et in [(wb_re,"wb"),(ml_re,"mem"),(ms_re,"mem"),(br_re,"flush"),(jmp_re,"flush"),(flush_re,"flush")]:
            if pat.search(line):
                if cur: cur["events"].append((et,line))
                log.append((et,line)); matched=True; break
        if not matched:
            m = total_re.match(line)
            if m:
                total_cycles = int(m.group(1))
                log.append(("done", line))
                continue
            if "EXECUTION FINISHED" in line:
                in_final = True
                log.append(("done", line))
                continue
            if "Final Register State" in line:
                in_final = True
                log.append(("info", line)); continue
            if in_final:
                m2=freg_re.match(line)
                if m2: final_regs[f"R{m2.group(1)}"]=m2.group(2)
                m_pc=fpc_re.match(line)
                if m_pc: final_pc=int(m_pc.group(1))
                m3=fmem_re.match(line)
                if m3: final_mem[f"{m3.group(1)}[{m3.group(2)}]"]=m3.group(3)
                log.append(("info",line))
            elif cur: log.append(("info",line))
    if cur: cycles.append(cur)
    return {"cycles":cycles,"log":log,"parsed_insts":parsed_insts,
            "final_regs":final_regs,"final_mem":final_mem,"final_pc":final_pc,
            "total_cycles":total_cycles}

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════════════════════════════════════════
class PipelineApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("CPU Pipeline Simulator — GUC CSEN601")
        self.geometry("1620x900")
        self.minsize(1200, 700)
        self.configure(fg_color=BG0)

        self.data        = None
        self.cycle_idx   = 0
        self.auto_play   = False
        self.auto_delay  = 0.6
        self._auto_thread = None

        self._build_ui()
        self._sync_editor_from_disk()
        self._set_status("Loaded program.txt  ·  Press  ⟳ Load & Run  to simulate.")

    # ─── UI construction ──────────────────────────────────────────────────────
    def _build_ui(self):
        # ── top bar ──
        top = ctk.CTkFrame(self, fg_color=BG1, corner_radius=0, height=52)
        top.pack(fill="x", side="top")
        top.pack_propagate(False)

        ctk.CTkLabel(top, text=" ⚡ Pipeline Simulator",
                     font=ctk.CTkFont("Courier New", 18, "bold"),
                     text_color=NVIDIA).pack(side="left", padx=16)
        ctk.CTkLabel(top, text="GUC · CSEN601 · Package 1",
                     font=ctk.CTkFont("Courier New", 11),
                     text_color=TEXT2).pack(side="left", padx=4)

        # controls on right
        ctrl = ctk.CTkFrame(top, fg_color="transparent")
        ctrl.pack(side="right", padx=12)

        self.speed_label = ctk.CTkLabel(ctrl, text="Speed", font=ctk.CTkFont(size=11), text_color=TEXT2)
        self.speed_label.grid(row=0, column=0, padx=(0,4))
        self.speed_slider = ctk.CTkSlider(ctrl, from_=100, to=2000, width=100,
                                          button_color=NVIDIA, button_hover_color=GREEN,
                                          progress_color=NVIDIA_D,
                                          command=self._on_speed)
        self.speed_slider.set(600)
        self.speed_slider.grid(row=0, column=1, padx=4)

        self.btn_step = ctk.CTkButton(ctrl, text="▶ Step", width=80,
                                      fg_color=BG3, hover_color=BG2, border_color=BORDER,
                                      border_width=1, text_color=TEXT,
                                      font=ctk.CTkFont(size=12),
                                      command=self._step_fwd)
        self.btn_step.grid(row=0, column=2, padx=4)

        self.btn_back = ctk.CTkButton(ctrl, text="◀ Back", width=80,
                                      fg_color=BG3, hover_color=BG2, border_color=BORDER,
                                      border_width=1, text_color=TEXT,
                                      font=ctk.CTkFont(size=12),
                                      command=self._step_back)
        self.btn_back.grid(row=0, column=3, padx=4)

        self.btn_play = ctk.CTkButton(ctrl, text="⏵ Auto", width=80,
                                      fg_color=NVIDIA_D, hover_color="#2a4400",
                                      border_color=NVIDIA, border_width=1,
                                      text_color=NVIDIA,
                                      font=ctk.CTkFont(size=12, weight="bold"),
                                      command=self._toggle_play)
        self.btn_play.grid(row=0, column=4, padx=4)

        self.btn_load = ctk.CTkButton(ctrl, text="⟳ Load & Run", width=110,
                                      fg_color="#003a00", hover_color="#004d00",
                                      border_color=GREEN, border_width=1,
                                      text_color=GREEN,
                                      font=ctk.CTkFont(size=12, weight="bold"),
                                      command=self._load_and_run)
        self.btn_load.grid(row=0, column=5, padx=(8,0))

        # ── status bar ──
        self.status_var = ctk.StringVar(value="")
        status = ctk.CTkFrame(self, fg_color=BG1, corner_radius=0, height=26)
        status.pack(fill="x", side="bottom")
        status.pack_propagate(False)
        ctk.CTkLabel(status, textvariable=self.status_var,
                     font=ctk.CTkFont("Courier New", 11),
                     text_color=TEXT2, anchor="w").pack(side="left", padx=10)
        self.cycle_badge = ctk.CTkLabel(status, text="Cycle —",
                                        font=ctk.CTkFont("Courier New", 11, "bold"),
                                        text_color=NVIDIA)
        self.cycle_badge.pack(side="right", padx=12)

        # ── main body ──
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=0, pady=0)
        body.columnconfigure(0, weight=0, minsize=290)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, weight=0, minsize=380)
        body.rowconfigure(0, weight=1)

        # LEFT
        self._build_left(body)
        # CENTER
        self._build_center(body)
        # RIGHT
        self._build_right(body)

    # ── LEFT: editor + instruction memory ─────────────────────────────────────
    def _build_left(self, parent):
        left = ctk.CTkFrame(parent, fg_color=BG1, corner_radius=0,
                            border_color=BORDER, border_width=1)
        left.grid(row=0, column=0, sticky="nsew")
        left.rowconfigure(1, weight=2)
        left.rowconfigure(3, weight=1)
        left.columnconfigure(0, weight=1)

        self._section_title(left, "Assembly Program", 0)

        self.editor = ctk.CTkTextbox(left, font=ctk.CTkFont("Courier New", 12),
                                     fg_color=BG0, text_color=TEXT,
                                     border_width=0, corner_radius=0,
                                     wrap="none")
        self.editor.grid(row=1, column=0, sticky="nsew")

        btn_bar = ctk.CTkFrame(left, fg_color=BG2, corner_radius=0, height=36)
        btn_bar.grid(row=2, column=0, sticky="ew")
        btn_bar.pack_propagate(False)
        ctk.CTkButton(btn_bar, text="↻ Reload program.txt",
                      fg_color=BG3, hover_color=BG2,
                      border_color=BORDER, border_width=1,
                      text_color=TEXT, height=28,
                      font=ctk.CTkFont(size=11),
                      command=self._reload_program_file).pack(side="left", fill="x", expand=True, padx=(8, 4), pady=4)
        ctk.CTkButton(btn_bar, text="⟳  Recompile & Run",
                      fg_color=NVIDIA_D, hover_color="#2d5200",
                      border_color=NVIDIA, border_width=1,
                      text_color=NVIDIA, height=28,
                      font=ctk.CTkFont(size=11, weight="bold"),
                      command=self._load_and_run).pack(side="left", fill="x", expand=True, padx=(4, 8), pady=4)

        self._section_title(left, "Instruction Memory", 3)

        self.imem_box = ctk.CTkTextbox(left, font=ctk.CTkFont("Courier New", 11),
                                       fg_color=BG0, text_color=TEXT2,
                                       border_width=0, corner_radius=0,
                                       state="disabled")
        self.imem_box.grid(row=4, column=0, sticky="nsew")
        left.rowconfigure(4, weight=1)

    # ── CENTER: pipeline visualization ────────────────────────────────────────
    def _build_center(self, parent):
        center = ctk.CTkFrame(parent, fg_color=BG0, corner_radius=0)
        center.grid(row=0, column=1, sticky="nsew")
        center.rowconfigure(1, weight=1)
        center.columnconfigure(0, weight=1)

        # Cycle bar
        cbar = ctk.CTkFrame(center, fg_color=BG1, corner_radius=0,
                            border_color=BORDER, border_width=1, height=48)
        cbar.grid(row=0, column=0, sticky="ew")
        cbar.pack_propagate(False)
        self.cycle_lbl = ctk.CTkLabel(cbar, text="Cycle 0",
                                      font=ctk.CTkFont("Courier New", 22, "bold"),
                                      text_color=NVIDIA)
        self.cycle_lbl.pack(side="left", padx=20)
        self.pc_lbl = ctk.CTkLabel(cbar, text="PC: —",
                                   font=ctk.CTkFont("Courier New", 13),
                                   text_color=TEXT2)
        self.pc_lbl.pack(side="left", padx=8)

        self.stat_lbl = ctk.CTkLabel(cbar, text="",
                                     font=ctk.CTkFont("Courier New", 11),
                                     text_color=TEXT2)
        self.stat_lbl.pack(side="right", padx=20)

        # Scrollable pipeline area
        scroll = ctk.CTkScrollableFrame(center, fg_color=BG0, corner_radius=0)
        scroll.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        scroll.columnconfigure(0, weight=1)
        self.pipeline_frame = scroll

        # Build the 5 stage cards
        self.stage_cards = {}
        stages_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        stages_frame.pack(fill="x", padx=16, pady=(16,8))
        for i, sid in enumerate(["IF","ID","EX","MEM","WB"]):
            stages_frame.columnconfigure(i, weight=1)
            card = self._make_stage_card(stages_frame, sid)
            card.grid(row=0, column=i, padx=5, pady=0, sticky="nsew")
            self.stage_cards[sid] = card

        # Hazard area
        self.hazard_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.hazard_frame.pack(fill="x", padx=16, pady=4)

        # Register snapshot row
        reg_frame = ctk.CTkFrame(scroll, fg_color=BG1,
                                 corner_radius=8, border_color=BORDER, border_width=1)
        reg_frame.pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(reg_frame, text="  Register Snapshot",
                     font=ctk.CTkFont("Courier New", 11, "bold"),
                     text_color=TEXT2).pack(anchor="w", padx=8, pady=(6,2))
        self.reg_snap_frame = ctk.CTkFrame(reg_frame, fg_color="transparent")
        self.reg_snap_frame.pack(fill="x", padx=8, pady=(0,8))

        # Pipeline flow bar
        flow_outer = ctk.CTkFrame(scroll, fg_color=BG1,
                                  corner_radius=8, border_color=BORDER, border_width=1)
        flow_outer.pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(flow_outer, text="  Pipeline Flow",
                     font=ctk.CTkFont("Courier New", 11, "bold"),
                     text_color=TEXT2).pack(anchor="w", padx=8, pady=(6,2))
        flow_inner = ctk.CTkFrame(flow_outer, fg_color="transparent")
        flow_inner.pack(fill="x", padx=8, pady=(0,8))
        self.flow_labels = {}   # sid -> (frame, label)
        for i, sid in enumerate(["IF","ID","EX","MEM","WB"]):
            flow_inner.columnconfigure(i*2, weight=1)
            frm = ctk.CTkFrame(flow_inner, fg_color=BG3, corner_radius=6,
                               border_color=BORDER, border_width=1,
                               width=80, height=32)
            frm.grid(row=0, column=i*2, padx=3, pady=4)
            frm.pack_propagate(False)
            lbl = ctk.CTkLabel(frm, text=sid,
                               font=ctk.CTkFont("Courier New", 12, "bold"),
                               fg_color="transparent", text_color=TEXT2)
            lbl.pack(expand=True)
            self.flow_labels[sid] = (frm, lbl)
            if i < 4:
                ctk.CTkLabel(flow_inner, text="→",
                             font=ctk.CTkFont(size=14), text_color=TEXT2).grid(row=0, column=i*2+1)

    def _make_stage_card(self, parent, sid):
        bg, accent = STAGE_COLORS[sid]
        frame = ctk.CTkFrame(parent, fg_color=BG2, corner_radius=10,
                             border_color=BORDER, border_width=1)
        frame.columnconfigure(0, weight=1)

        # header
        hdr = ctk.CTkFrame(frame, fg_color=BG3, corner_radius=0, height=30)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text=sid,
                     font=ctk.CTkFont("Courier New", 13, "bold"),
                     text_color=accent).pack(side="left", padx=10)
        stage_names = {"IF":"Fetch","ID":"Decode","EX":"Execute","MEM":"Memory","WB":"Write Back"}
        ctk.CTkLabel(hdr, text=stage_names[sid],
                     font=ctk.CTkFont(size=10), text_color=TEXT2).pack(side="left")

        # body labels
        inst_lbl = ctk.CTkLabel(frame, text="— empty —",
                                font=ctk.CTkFont("Courier New", 12, "bold"),
                                text_color=TEXT2, wraplength=160)
        inst_lbl.pack(pady=(8,2), padx=8)

        info_lbl = ctk.CTkLabel(frame, text="",
                                font=ctk.CTkFont("Courier New", 10),
                                text_color=TEXT2, wraplength=160, justify="left")
        info_lbl.pack(pady=(0,8), padx=8)

        evt_lbl = ctk.CTkLabel(frame, text="",
                               font=ctk.CTkFont("Courier New", 10),
                               text_color=accent, wraplength=160, justify="left")
        evt_lbl.pack(pady=(0,6), padx=8)

        frame._inst_lbl = inst_lbl
        frame._info_lbl = info_lbl
        frame._evt_lbl  = evt_lbl
        frame._accent   = accent
        frame._sid      = sid
        return frame

    # ── RIGHT: stats + registers + memory + log ───────────────────────────────
    def _build_right(self, parent):
        right = ctk.CTkFrame(parent, fg_color=BG1, corner_radius=0,
                             border_color=BORDER, border_width=1)
        right.grid(row=0, column=2, sticky="nsew")
        right.rowconfigure(2, weight=0)
        right.rowconfigure(4, weight=1)
        right.rowconfigure(6, weight=2)
        right.columnconfigure(0, weight=1)

        # ── Stats ──
        self._section_title(right, "Statistics", 0)
        stats_grid = ctk.CTkFrame(right, fg_color="transparent")
        stats_grid.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        stats_grid.columnconfigure((0,1,2,3), weight=1)
        self.stat_cards = {}
        for i, (key, label) in enumerate([("cycles","Cycles"),("completed","Done"),
                                           ("hazards","Hazards"),("flushes","Flushes")]):
            c = ctk.CTkFrame(stats_grid, fg_color=BG2, corner_radius=8,
                             border_color=BORDER, border_width=1)
            c.grid(row=0, column=i, padx=3, pady=2, sticky="ew")
            val = ctk.CTkLabel(c, text="0",
                               font=ctk.CTkFont("Courier New", 18, "bold"),
                               text_color=NVIDIA)
            val.pack(pady=(6,0))
            ctk.CTkLabel(c, text=label, font=ctk.CTkFont(size=9),
                         text_color=TEXT2).pack(pady=(0,6))
            self.stat_cards[key] = val

        # ── Registers ──
        self._section_title(right, "Registers", 2)
        reg_scroll = ctk.CTkScrollableFrame(right, fg_color=BG0, corner_radius=0,
                                            height=240, width=360)
        reg_scroll.grid(row=3, column=0, sticky="nsew", padx=6, pady=0)
        reg_scroll.grid_columnconfigure(0, weight=1)
        self.reg_frame = reg_scroll
        self._build_reg_grid()

        # ── Data Memory ──
        self._section_title(right, "Data Memory", 4)
        self.mem_box = ctk.CTkTextbox(right, font=ctk.CTkFont("Courier New", 12),
                                      fg_color=BG0, text_color=CYAN,
                                      border_width=0, corner_radius=0,
                                      height=130, state="disabled")
        self.mem_box.grid(row=5, column=0, sticky="nsew")

        # ── Log ──
        self._section_title(right, "Execution Log", 6)
        self.log_box = ctk.CTkTextbox(right, font=ctk.CTkFont("Courier New", 11),
                                      fg_color=BG0, text_color=TEXT2,
                                      border_width=0, corner_radius=0,
                                      state="disabled")
        self.log_box.grid(row=7, column=0, sticky="nsew")
        right.rowconfigure(7, weight=3)

        # configure tag colors (must use underlying tk Text widget)
        t = self.log_box._textbox
        t.tag_config("cycle",  foreground=NVIDIA, font=("Courier New", 11, "bold"))
        t.tag_config("wb",     foreground=GREEN)
        t.tag_config("mem",    foreground=CYAN)
        t.tag_config("flush",  foreground=RED)
        t.tag_config("hazard", foreground=AMBER)
        t.tag_config("done",   foreground=NVIDIA, font=("Courier New", 11, "bold"))
        t.tag_config("parse",  foreground=PURPLE)
        t.tag_config("info",   foreground=TEXT2)
        t.tag_config("err",    foreground=RED)

    def _build_reg_grid(self):
        for w in self.reg_frame.winfo_children():
            w.destroy()
        self.reg_labels = {}
        cols = 2
        for c in range(cols):
            self.reg_frame.grid_columnconfigure(c, weight=1, uniform="regcol")
        for i in range(32):
            row, col = i // cols, i % cols
            lbl = ctk.CTkLabel(
                self.reg_frame,
                text=f"R{i:2d}   0",
                font=ctk.CTkFont("Courier New", 14),
                text_color=TEXT,
                fg_color=BG2,
                corner_radius=4,
                anchor="w",
                height=34,
                width=170,
            )
            lbl.grid(row=row, column=col, padx=(4, 6), pady=3, sticky="ew")
            self.reg_labels[i] = lbl

    def _section_title(self, parent, text, row):
        f = ctk.CTkFrame(parent, fg_color=BG3, corner_radius=0, height=24)
        f.grid(row=row, column=0, sticky="ew")
        f.pack_propagate(False)
        ctk.CTkLabel(f, text=f"  {text}",
                     font=ctk.CTkFont("Courier New", 10, "bold"),
                     text_color=TEXT2, anchor="w").pack(side="left", fill="both")

    # ─── program.txt sync (file on disk is the source of truth) ───────────────
    def _read_program_from_disk(self):
        if os.path.isfile(PROG):
            with open(PROG, encoding="utf-8") as f:
                return f.read()
        return DEFAULT_PROGRAM

    def _sync_editor_from_disk(self):
        """Load src/program.txt into the editor."""
        text = self._read_program_from_disk()
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)
        return text

    def _reload_program_file(self):
        self._sync_editor_from_disk()
        self._set_status(f"Reloaded {PROG}")

    def _save_editor_to_disk(self):
        text = self.editor.get("1.0", "end")
        with open(PROG, "w", encoding="utf-8") as f:
            f.write(text)
        return text

    # ─── Load & Run ───────────────────────────────────────────────────────────
    def _load_and_run(self):
        self._stop_play()
        # Always use the current program.txt (edits in IDE / external editor)
        prog = self._sync_editor_from_disk()
        self._set_status("Compiling…")
        self.update()
        ok, msg, binary = compile_binary()
        if not ok:
            self._set_status(f"Compile error: {msg[:100]}")
            messagebox.showerror("Compile Error", msg)
            return
        self._set_status("Running simulation…")
        self.update()
        try:
            lines, err = run_simulation(prog, binary)
        except subprocess.TimeoutExpired:
            self._set_status("Simulation timed out.")
            return
        except FileNotFoundError:
            self._set_status(f"Binary not found: {BIN}")
            return
        self.data = parse_output(lines)
        self.cycle_idx = 0
        self._update_all()
        nc = len(self.data["cycles"])
        self._set_status(f"{nc} cycles  ·  {len(self.data['parsed_insts'])} instructions  ·  "
                         f"← → to step  ·  ⏵ Auto to play")
        self._render_imem()
        self._populate_log()

    # ─── Navigation ──────────────────────────────────────────────────────────
    def _step_fwd(self):
        if not self.data: return
        if self.cycle_idx < len(self.data["cycles"])-1:
            self.cycle_idx += 1
            self._update_all()

    def _step_back(self):
        if not self.data: return
        if self.cycle_idx > 0:
            self.cycle_idx -= 1
            self._update_all()

    def _toggle_play(self):
        if self.auto_play:
            self._stop_play()
        else:
            self._start_play()

    def _start_play(self):
        self.auto_play = True
        self.btn_play.configure(text="⏸ Pause", fg_color="#3b0f0f",
                                border_color=RED, text_color=RED)
        self._auto_thread = threading.Thread(target=self._auto_loop, daemon=True)
        self._auto_thread.start()

    def _stop_play(self):
        self.auto_play = False
        self.btn_play.configure(text="⏵ Auto", fg_color=NVIDIA_D,
                                border_color=NVIDIA, text_color=NVIDIA)

    def _auto_loop(self):
        while self.auto_play and self.data:
            nc = len(self.data["cycles"])
            if self.cycle_idx >= nc-1:
                self.after(0, self._stop_play)
                break
            self.after(0, self._step_fwd)
            time.sleep(self.auto_delay / 1000)

    def _on_speed(self, val):
        self.auto_delay = float(val)
        ms = int(val)
        self.speed_label.configure(text=f"Speed {ms}ms")

    # ─── Rendering ────────────────────────────────────────────────────────────
    def _update_all(self):
        if not self.data or not self.data["cycles"]: return
        cy = self.data["cycles"][self.cycle_idx]
        self._render_cycle_header(cy)
        self._render_stage_cards(cy)
        self._render_hazards(cy)
        self._render_reg_snapshot(cy)
        self._render_registers(cy)
        self._render_memory(cy)
        self._render_stats()
        self._highlight_log(cy)

    def _render_cycle_header(self, cy):
        self.cycle_lbl.configure(text=f"Cycle {cy['cycle']}")
        self.cycle_badge.configure(text=f"Cycle {cy['cycle']} / {len(self.data['cycles'])}")

    def _get_inst_label(self, stages, sid):
        state = stages.get(sid, "Empty")
        if "Active" in state or "Cycle" in state:
            return state
        return None

    def _render_stage_cards(self, cy):
        for sid, card in self.stage_cards.items():
            state = cy["stages"].get(sid, "Empty")
            active = "Active" in state or "Cycle" in state
            bg, accent = STAGE_COLORS[sid]

            card.configure(fg_color=bg if active else BG2,
                           border_color=accent if active else BORDER)
            card._inst_lbl.configure(text=state if active else "— empty —",
                                     text_color=accent if active else TEXT2)

            # info
            info = ""
            for etype, emsg in cy.get("events", []):
                stage_of = {"wb":"WB","mem":"MEM","flush":"EX"}.get(etype,"")
                if stage_of == sid:
                    info += emsg.split(":",1)[-1].strip()[:40] + "\n"
            card._info_lbl.configure(text=info.strip())

            # events
            evts = [e for t,e in cy.get("events",[]) if
                    (t=="wb" and sid=="WB") or
                    (t=="mem" and sid=="MEM") or
                    (t=="flush" and sid=="EX")]
            card._evt_lbl.configure(
                text="\n".join(e.split(":",1)[-1].strip()[:35] for e in evts[:2]),
                text_color=RED if any(t=="flush" for t,_ in cy.get("events",[])
                                      if {"flush":"EX"}.get(t)==sid) else accent
            )

            # flow bar
            fl_frm, fl_lbl = self.flow_labels[sid]
            if active:
                fl_frm.configure(fg_color=bg, border_color=accent, border_width=2)
                fl_lbl.configure(text_color=accent)
            else:
                fl_frm.configure(fg_color=BG3, border_color=BORDER, border_width=1)
                fl_lbl.configure(text_color=TEXT2)

    def _render_hazards(self, cy):
        for w in self.hazard_frame.winfo_children(): w.destroy()
        events = cy.get("events", [])
        for etype, emsg in events:
            if etype == "flush":
                color, icon = RED, "⚡ FLUSH"
            elif etype == "mem":
                color, icon = CYAN, "💾 MEM"
            elif etype == "wb":
                color, icon = GREEN, "✔ WB"
            else:
                continue
            pill = ctk.CTkFrame(self.hazard_frame, fg_color=BG2,
                                corner_radius=6, border_color=color, border_width=1)
            pill.pack(side="left", padx=4, pady=2)
            ctk.CTkLabel(pill, text=f"{icon}: {emsg.split(':',1)[-1].strip()[:50]}",
                         font=ctk.CTkFont("Courier New", 10),
                         text_color=color).pack(padx=8, pady=3)

    def _render_reg_snapshot(self, cy):
        for w in self.reg_snap_frame.winfo_children(): w.destroy()
        regs = cy.get("regs", {})
        if not regs:
            ctk.CTkLabel(self.reg_snap_frame, text="No register data this cycle",
                         font=ctk.CTkFont("Courier New", 10),
                         text_color=TEXT2).pack(side="left")
            return
        for rname, rval in regs.items():
            color = NVIDIA if rval != "0" else TEXT2
            f = ctk.CTkFrame(self.reg_snap_frame, fg_color=BG3,
                             corner_radius=5, border_color=BORDER, border_width=1)
            f.pack(side="left", padx=3, pady=2)
            ctk.CTkLabel(f, text=f"{rname}={rval}",
                         font=ctk.CTkFont("Courier New", 10, "bold"),
                         text_color=color).pack(padx=6, pady=3)

    def _register_values_up_to(self, cycle_idx):
        """Reconstruct register file from WB events through current cycle."""
        regs = {f"R{i}": "0" for i in range(32)}
        for cy in self.data["cycles"][:cycle_idx + 1]:
            for etype, emsg in cy.get("events", []):
                if etype == "wb":
                    m = re.search(r"R(\d+) = (-?\d+)", emsg)
                    if m:
                        regs[f"R{m.group(1)}"] = m.group(2)
        if cycle_idx >= len(self.data["cycles"]) - 1:
            for k, v in self.data.get("final_regs", {}).items():
                regs[k] = v
        return regs

    def _data_memory_up_to(self, cycle_idx):
        """All data-memory words written up to this cycle (addr >= 1024)."""
        dmem = {}
        for cy in self.data["cycles"][:cycle_idx + 1]:
            for etype, emsg in cy.get("events", []):
                m = re.search(r"Data Memory \[(\d+)\] = (-?\d+)", emsg)
                if m:
                    dmem[int(m.group(1))] = m.group(2)
        if cycle_idx >= len(self.data["cycles"]) - 1:
            for k, v in self.data.get("final_mem", {}).items():
                if k.startswith("Data"):
                    addr = int(re.search(r"\[(\d+)\]", k).group(1))
                    dmem[addr] = v
        return dmem

    def _render_registers(self, cy):
        regs = self._register_values_up_to(self.cycle_idx)
        changed = set()
        for etype, emsg in cy.get("events", []):
            if etype == "wb":
                m = re.search(r"R(\d+)", emsg)
                if m: changed.add(int(m.group(1)))
        for i, lbl in self.reg_labels.items():
            rkey = f"R{i}"
            val = regs.get(rkey, "0")
            snap = cy.get("regs", {})
            if rkey in snap:
                val = snap[rkey]
            highlight = i in changed
            nonzero = val not in ("0", "?", "")
            lbl.configure(
                text=f"R{i:2d}   {val}",
                fg_color=NVIDIA_D if highlight else BG2,
                text_color=NVIDIA if (highlight or nonzero) else TEXT,
            )

    def _render_memory(self, cy):
        dmem = self._data_memory_up_to(self.cycle_idx)
        self.mem_box.configure(state="normal")
        self.mem_box.delete("1.0", "end")
        if not dmem:
            self.mem_box.insert("end", "  (no data writes yet)\n")
        else:
            for addr in sorted(dmem):
                self.mem_box.insert("end", f"  Data[{addr}] = {dmem[addr]}\n")
        self.mem_box.configure(state="disabled")

    def _render_stats(self):
        nc = self.cycle_idx + 1
        self.stat_cards["cycles"].configure(text=str(nc))
        # count completed WB events up to this cycle
        done = sum(1 for cy in self.data["cycles"][:nc]
                   for et, _ in cy.get("events",[]) if et=="wb")
        hazards = sum(1 for cy in self.data["cycles"][:nc]
                      for et, _ in cy.get("events",[]) if et in ("mem",))
        flushes = sum(1 for cy in self.data["cycles"][:nc]
                      for et, _ in cy.get("events",[]) if et=="flush")
        self.stat_cards["completed"].configure(text=str(done))
        self.stat_cards["hazards"].configure(text=str(hazards))
        self.stat_cards["flushes"].configure(text=str(flushes))

    def _format_final_registers_block(self):
        """All 32 registers + PC for the execution log footer."""
        lines = ["", "=== Final Register State (All Registers) ==="]
        pc = self.data.get("final_pc", 0)
        lines.append(f"PC: {pc}")
        final = self.data.get("final_regs", {})
        for i in range(32):
            key = f"R{i}"
            val = final.get(key)
            if val is None and self.data.get("cycles"):
                regs = self._register_values_up_to(len(self.data["cycles"]) - 1)
                val = regs.get(key, "0")
            lines.append(f"{key}: {val if val is not None else '0'}")
        return "\n".join(lines) + "\n"

    def _populate_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        t = self.log_box._textbox
        for ltype, ltext in self.data["log"]:
            tag = ltype if ltype in ("cycle","wb","mem","flush","done","parse","info") else "info"
            t.insert("end", ltext + "\n", tag)
        if len(self.data.get("final_regs", {})) < 32:
            t.insert("end", self._format_final_registers_block(), "done")
        self.log_box.configure(state="disabled")

    def _highlight_log(self, cy):
        # Scroll log to current cycle
        t = self.log_box._textbox
        # find line matching this cycle
        pattern = f"Clock Cycle {cy['cycle']}"
        idx = t.search(pattern, "1.0", "end")
        if idx:
            t.see(idx)

    def _render_imem(self):
        self.imem_box.configure(state="normal")
        self.imem_box.delete("1.0", "end")
        for inst in self.data.get("parsed_insts", []):
            self.imem_box.insert("end",
                f"[{inst['addr']:2d}] {inst['hex']}  {inst['mnem']}\n")
        self.imem_box.configure(state="disabled")

    # ─── Helpers ──────────────────────────────────────────────────────────────
    def _set_status(self, msg):
        self.status_var.set(f"  {msg}")

# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not os.path.isdir(SRC):
        print(f"ERROR: src/ not found at {SRC}")
        print("Run this script from the ca/ directory.")
        sys.exit(1)
    app = PipelineApp()
    app.mainloop()