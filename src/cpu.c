#include <stdio.h>
#include "cpu.h"

/* -----------------------------------------------------------------------
   Global state
   ----------------------------------------------------------------------- */
int memory[2048]            = {0};
bool data_memory_modified[2048] = {0};
int registers[32]  = {0};
int pc             = 0;
int clock_cycles   = 1;

bool flush_pipeline        = false;
int  new_pc                = 0;
bool mem_active_this_cycle = false;
bool mem_stage_this_cycle  = false;
bool fetched_this_cycle    = false;

/*
 * Pipeline latches
 * ----------------
 * IF_latch : 1-cycle buffer – holds an instruction that was fetched this
 *            cycle and will move to IF_ID at the start of the next cycle.
 *            "IF Active" in the display means IF_latch.is_active.
 * IF_ID    : the instruction currently in the Decode stage (2 cycles).
 *            "ID Active (N/2)" in the display.
 * ID_EX    : the instruction currently in the Execute stage (2 cycles).
 * EX_MEM   : the instruction currently in the Memory stage (1 cycle).
 * MEM_WB   : the instruction currently in the Write-Back stage (1 cycle).
 *
 
 */
PipelineRegister IF_latch = {0};
PipelineRegister IF_ID    = {0};
PipelineRegister ID_EX    = {0};
PipelineRegister EX_MEM   = {0};
PipelineRegister MEM_WB   = {0};

/* -----------------------------------------------------------------------
   Helpers
   ----------------------------------------------------------------------- */
static int sign_extend_18(int imm) {
    if (imm & 0x20000) return imm | 0xFFFC0000;
    return imm;
}

static int dest_of(const PipelineRegister *p) {
    if (!p->is_active) return -1;
    switch (p->opcode) {
        case 0: case 1:                          return p->r3;
        case 2: case 3: case 5: case 6:
        case 8: case 9: case 10:                 return p->r1;
        default:                                 return -1;
    }
}

static int fwd_value(const PipelineRegister *p) {
    return (p->opcode == 10) ? p->mem_data : p->alu_result;
}

static bool is_if_half_cycle(void)  { return (clock_cycles % 2) == 1; }
static bool is_mem_half_cycle(void) { return (clock_cycles % 2) == 0; }

/* -----------------------------------------------------------------------
   Stage 5 – Write Back  (1 cycle)
   ----------------------------------------------------------------------- */
void writeback() {
    if (!MEM_WB.is_active) return;
    int dest = dest_of(&MEM_WB);
    if (dest > 0) {
        int data = fwd_value(&MEM_WB);
        registers[dest] = data;
        printf("Register update (WB stage): R%d = %d\n", dest, data);
    } else if (dest == 0) {
        printf("Register update (WB stage): R0 write suppressed (stays 0)\n");
    }
    MEM_WB.is_active = false;
}

/* -----------------------------------------------------------------------
   Stage 4 – Memory  (1 cycle)
   ----------------------------------------------------------------------- */
void memory_stage() {
    mem_active_this_cycle = false;
    mem_stage_this_cycle  = false;
    if (!EX_MEM.is_active) return;
    /* MEM-half cycles only (even). Run after execute() so an instruction
     * that enters EX_MEM this cycle can complete MEM in the same cycle. */
    if (!is_mem_half_cycle()) return;

    mem_stage_this_cycle = true;

    if (EX_MEM.opcode == 10) {
        mem_active_this_cycle = true;
        EX_MEM.mem_data = memory[EX_MEM.alu_result];
        printf("Memory update (MEM stage): Data Memory [%d] = %d (load to R%d)\n",
               EX_MEM.alu_result, EX_MEM.mem_data, EX_MEM.r1);
    } else if (EX_MEM.opcode == 11) {
        mem_active_this_cycle = true;
        memory[EX_MEM.alu_result] = EX_MEM.valR1;
        data_memory_modified[EX_MEM.alu_result] = true;
        printf("Memory update (MEM stage): Data Memory [%d] = %d (store from R%d)\n",
               EX_MEM.alu_result, EX_MEM.valR1, EX_MEM.r1);
    }

    MEM_WB = EX_MEM;
    MEM_WB.cycles_in_stage = 1;
    EX_MEM.is_active = false;
}

/* -----------------------------------------------------------------------
   Stage 3 – Execute  (2 cycles)
   ----------------------------------------------------------------------- */
void execute() {
    if (!ID_EX.is_active) return;

    if (ID_EX.cycles_in_stage == 1) {
        ID_EX.cycles_in_stage = 2;
        return;
    }

    /* Data forwarding from MEM/WB */
    int val1 = registers[ID_EX.r1];
    int val2 = registers[ID_EX.r2];

    if (EX_MEM.is_active) {
        int dest = dest_of(&EX_MEM);
        if (dest > 0) {
            int fv = fwd_value(&EX_MEM);
            if (dest == ID_EX.r1) val1 = fv;
            if (dest == ID_EX.r2) val2 = fv;
        }
    }
    if (MEM_WB.is_active) {
        int dest = dest_of(&MEM_WB);
        if (dest > 0) {
            int fv = fwd_value(&MEM_WB);
            if (dest == ID_EX.r1) val1 = fv;
            if (dest == ID_EX.r2) val2 = fv;
        }
    }

    switch (ID_EX.opcode) {
        case 0:  ID_EX.alu_result = val1 + val2; break;
        case 1:  ID_EX.alu_result = val1 - val2; break;
        case 2:  ID_EX.alu_result = val2 * ID_EX.imm; break;
        case 3:  ID_EX.alu_result = val2 + ID_EX.imm; break;
        case 4:
            if (val1 != val2) {
                flush_pipeline = true;
                new_pc = (ID_EX.pc + 1) + ID_EX.imm;
                printf("EX stage output: branch taken, new PC = %d\n", new_pc);
            }
            break;
        case 5:  ID_EX.alu_result = val2 & ID_EX.imm; break;
        case 6:  ID_EX.alu_result = val2 ^ ID_EX.imm; break;
        case 7:
            flush_pipeline = true;
            new_pc = ((ID_EX.pc + 1) & 0xF0000000) |
                     (ID_EX.address  & 0x0FFFFFFF);
            printf("EX stage output: jump taken, new PC = %d\n", new_pc);
            break;
        case 8:  ID_EX.alu_result = (int)((unsigned)val2 << ID_EX.shamt); break;
        case 9:  ID_EX.alu_result = (int)((unsigned)val2 >> ID_EX.shamt); break;
        case 10:
        case 11:
            ID_EX.alu_result = val2 + ID_EX.imm;
            ID_EX.valR1      = val1;
            break;
    }

    EX_MEM = ID_EX;
    EX_MEM.cycles_in_stage = 1;
    ID_EX.is_active = false;
}

/* -----------------------------------------------------------------------
   Stage 2 – Decode  (2 cycles)
   ----------------------------------------------------------------------- */
void decode() {
    if (!IF_ID.is_active) return;

    if (IF_ID.cycles_in_stage == 1) {
        IF_ID.cycles_in_stage = 2;
        return;
    }

    int inst    = IF_ID.instruction;
    IF_ID.opcode  = (unsigned int)inst >> 28;
    IF_ID.r1      = (inst >> 23) & 0x1F;
    IF_ID.r2      = (inst >> 18) & 0x1F;
    IF_ID.r3      = (inst >> 13) & 0x1F;
    IF_ID.shamt   =  inst        & 0x1FFF;
    IF_ID.imm     = sign_extend_18(inst & 0x3FFFF);
    IF_ID.address =  inst        & 0x0FFFFFFF;
    IF_ID.valR1   = registers[IF_ID.r1];
    IF_ID.valR2   = registers[IF_ID.r2];

    ID_EX = IF_ID;
    ID_EX.cycles_in_stage = 1;
    IF_ID.is_active = false;
}

/* -----------------------------------------------------------------------
   Stage 1 – Fetch  (1 cycle)

   The fetch stage works in two sub-steps each cycle:

   Step A – Advance: if IF_latch has a fetched instruction and IF_ID is
            now free, move it into IF_ID (start decode).

   Step B – Fetch:   only on odd (IF-half) cycles, when MEM is not using
            the bus, IF_latch is empty, and more instructions remain.

   Odd cycles  : IF, ID, EX, WB  (fetch allowed)
   Even cycles : ID, EX, MEM, WB (no fetch; MEM may use memory)
   ----------------------------------------------------------------------- */
void fetch() {
    fetched_this_cycle = false;

    /* Step A: move a latched instruction into decode when ID is free */
    if (IF_latch.is_active && !IF_ID.is_active) {
        IF_ID = IF_latch;
        IF_ID.cycles_in_stage = 1;
        IF_latch.is_active = false;
    }

    /* Step B: new fetch only on IF-half cycles */
    if (!is_if_half_cycle())                             return;
    if (mem_active_this_cycle)                           return;
    if (IF_latch.is_active)                              return;
    if (pc >= loaded_instruction_count || pc > 1023)   return;

    IF_latch.instruction     = memory[pc];
    IF_latch.pc              = pc;
    IF_latch.cycles_in_stage = 1;
    IF_latch.is_active       = true;
    fetched_this_cycle       = true;
    pc++;
}