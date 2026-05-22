#include <stdio.h>
#include <stdbool.h>
#include "cpu.h"
#include "parser.h"

/* -----------------------------------------------------------------------
   Printing helpers (Package 1 deliverables)
   ----------------------------------------------------------------------- */
static const char *opcode_name(int op) {
    static const char *names[] = {
        "ADD", "SUB", "MULI", "ADDI", "BNE", "ANDI", "XORI",
        "J", "SLL", "SRL", "LW", "SW"
    };
    if (op >= 0 && op <= 11) return names[op];
    return "???";
}

static int sign_extend_18_local(int imm) {
    if (imm & 0x20000) return imm | 0xFFFC0000;
    return imm;
}

static void decode_word(int inst, int *op, int *r1, int *r2, int *r3,
                        int *shamt, int *imm, int *addr) {
    *op    = (unsigned)inst >> 28;
    *r1    = (inst >> 23) & 0x1F;
    *r2    = (inst >> 18) & 0x1F;
    *r3    = (inst >> 13) & 0x1F;
    *shamt = inst & 0x1FFF;
    *imm   = sign_extend_18_local(inst & 0x3FFFF);
    *addr  = inst & 0x0FFFFFFF;
}

static void print_fields(int op, int r1, int r2, int r3, int shamt, int imm, int addr) {
    switch (op) {
        case 0: case 1:
            printf("    Operands: R%d, R%d -> R%d\n", r1, r2, r3);
            break;
        case 2: case 3: case 5: case 6:
            printf("    Operands: R%d, R%d, imm=%d\n", r1, r2, imm);
            break;
        case 4:
            printf("    Operands: R%d, R%d, offset=%d\n", r1, r2, imm);
            break;
        case 7:
            printf("    Jump address field: %d\n", addr);
            break;
        case 8: case 9:
            printf("    Operands: R%d, R%d, shamt=%d\n", r1, r2, shamt);
            break;
        case 10: case 11:
            printf("    Operands: R%d, base R%d, offset=%d (addr = R%d + %d)\n",
                   r1, r2, imm, r2, imm);
            break;
        default:
            break;
    }
}

static void print_pipeline_stage(const char *stage_name, const PipelineRegister *p,
                                 bool decoded_operands) {
    printf("  %s Stage:\n", stage_name);
    if (!p->is_active) {
        printf("    (empty)\n");
        return;
    }

    int op, r1, r2, r3, shamt, imm, addr;
    decode_word(p->instruction, &op, &r1, &r2, &r3, &shamt, &imm, &addr);

    printf("    Instruction: %s | PC=%d | word=0x%08X\n",
           opcode_name(op), p->pc, (unsigned)p->instruction);
    print_fields(op, r1, r2, r3, shamt, imm, addr);

    if (decoded_operands || p->valR1 || p->valR2) {
        printf("    Register file inputs: valR1(R%d)=%d, valR2(R%d)=%d\n",
               r1, p->valR1, r2, p->valR2);
    }

    if (p->cycles_in_stage > 0) {
        printf("    Time in stage: cycle %d/2\n", p->cycles_in_stage);
    }
}

static void print_cycle_report(void) {
    int op, r1, r2, r3, shamt, imm, addr;

    printf("\n========== Clock Cycle %d ==========\n", clock_cycles);

    /* (b) Pipeline stages */
    printf("Pipeline Stages:\n");

    /* IF */
    printf("  IF Stage:\n");
    if (fetched_this_cycle && IF_latch.is_active) {
        decode_word(IF_latch.instruction, &op, &r1, &r2, &r3, &shamt, &imm, &addr);
        printf("    Instruction fetched: %s | PC=%d | word=0x%08X\n",
               opcode_name(op), IF_latch.pc, (unsigned)IF_latch.instruction);
        print_fields(op, r1, r2, r3, shamt, imm, addr);
        printf("    Inputs:  instruction memory address %d\n", IF_latch.pc);
        printf("    Output:  instruction placed in IF latch; PC advanced\n");
    } else if (mem_active_this_cycle) {
        printf("    (idle — instruction memory busy; MEM uses data memory)\n");
    } else {
        printf("    (no new fetch this cycle)\n");
    }
    if (IF_latch.is_active && !fetched_this_cycle) {
        decode_word(IF_latch.instruction, &op, &r1, &r2, &r3, &shamt, &imm, &addr);
        printf("    IF latch holding: %s @ PC=%d (0x%08X)\n",
               opcode_name(op), IF_latch.pc, (unsigned)IF_latch.instruction);
    }

    print_pipeline_stage("ID", &IF_ID, true);

    /* EX */
    printf("  EX Stage:\n");
    if (!ID_EX.is_active) {
        printf("    (empty)\n");
    } else {
        decode_word(ID_EX.instruction, &op, &r1, &r2, &r3, &shamt, &imm, &addr);
        printf("    Instruction: %s | PC=%d | word=0x%08X\n",
               opcode_name(op), ID_EX.pc, (unsigned)ID_EX.instruction);
        print_fields(op, r1, r2, r3, shamt, imm, addr);
        printf("    Inputs:  valR1=%d, valR2=%d", ID_EX.valR1, ID_EX.valR2);
        if (op == 2 || op == 3 || op == 5 || op == 6 || op == 10 || op == 11)
            printf(", imm=%d", ID_EX.imm);
        if (op == 8 || op == 9) printf(", shamt=%d", ID_EX.shamt);
        printf("\n");
        printf("    Time in stage: cycle %d/2\n", ID_EX.cycles_in_stage);
        if (ID_EX.cycles_in_stage == 2) {
            printf("    Output:  ALU/branch result = %d\n", ID_EX.alu_result);
        } else {
            printf("    Output:  (executing — result next EX cycle)\n");
        }
    }

    /* MEM */
    printf("  MEM Stage:\n");
    if (mem_stage_this_cycle && MEM_WB.is_active) {
        const PipelineRegister *m = &MEM_WB;
        decode_word(m->instruction, &op, &r1, &r2, &r3, &shamt, &imm, &addr);
        printf("    Instruction: %s | PC=%d\n", opcode_name(op), m->pc);
        if (op == 10) {
            printf("    Inputs:  address=%d\n", m->alu_result);
            printf("    Output:  loaded value = %d -> destined for R%d\n",
                   m->mem_data, r1);
        } else if (op == 11) {
            printf("    Inputs:  address=%d, store data (R%d)=%d\n",
                   m->alu_result, r1, m->valR1);
            printf("    Output:  data memory[%d] updated\n", m->alu_result);
        } else {
            printf("    Inputs:  pass-through from EX (no data memory access)\n");
            printf("    Output:  ALU result %d forwarded to WB\n", m->alu_result);
        }
    } else if (EX_MEM.is_active) {
        decode_word(EX_MEM.instruction, &op, &r1, &r2, &r3, &shamt, &imm, &addr);
        printf("    Instruction: %s waiting for MEM-half cycle | PC=%d\n",
               opcode_name(op), EX_MEM.pc);
        printf("    Inputs:  ALU/address result = %d\n", EX_MEM.alu_result);
    } else {
        printf("    (empty)\n");
    }

    /* WB */
    printf("  WB Stage:\n");
    if (MEM_WB.is_active) {
        decode_word(MEM_WB.instruction, &op, &r1, &r2, &r3, &shamt, &imm, &addr);
        printf("    Instruction: %s | PC=%d\n", opcode_name(op), MEM_WB.pc);
        if (op == 10) {
            printf("    Inputs:  mem_data=%d for R%d\n", MEM_WB.mem_data, r1);
            printf("    Output:  will write R%d = %d next WB step\n", r1, MEM_WB.mem_data);
        } else {
            int dest = (op == 0 || op == 1) ? r3 : r1;
            int data = MEM_WB.alu_result;
            if (op == 10) data = MEM_WB.mem_data;
            printf("    Inputs:  result=%d\n", data);
            if (dest > 0)
                printf("    Output:  will write R%d = %d next WB step\n", dest, data);
            else if (dest == 0)
                printf("    Output:  R0 destination (value stays 0)\n");
            else
                printf("    Output:  no register writeback\n");
        }
    } else {
        printf("    (empty)\n");
    }

    printf("----------------------------------------\n");
}

static void print_final_registers(void) {
    printf("\n========== Final Register State (after last cycle) ==========\n");
    printf("PC: %d\n", pc);
    for (int i = 0; i < 32; i++) {
        printf("R%d: %d\n", i, registers[i]);
    }
}

static void print_final_memory(void) {
    int i;
    printf("\n========== Instruction Memory (loaded locations only) ==========\n");
    if (loaded_instruction_count == 0) {
        printf("(no instructions loaded)\n");
    } else {
        for (i = 0; i < loaded_instruction_count; i++) {
            printf("Instruction Memory [%4d]: 0x%08X\n", i, (unsigned)memory[i]);
        }
    }
    printf("\n========== Data Memory (modified locations only) ==========\n");
  {
    int any = 0;
    for (i = 1024; i < 2048; i++) {
        if (data_memory_modified[i]) {
            printf("Data Memory [%4d]: %d\n", i, memory[i]);
            any = 1;
        }
    }
    if (!any) printf("(no data memory stores occurred)\n");
  }
}

/* -----------------------------------------------------------------------
   main
   ----------------------------------------------------------------------- */
int main() {
    if (!load_program("program.txt")) {
        fprintf(stderr, "Failed to load program. Exiting.\n");
        return 1;
    }

    printf("=== STARTING PIPELINE EXECUTION ===\n");

    bool pipeline_active = true;
    const int max_cycles = 7 + (loaded_instruction_count > 0 ? (loaded_instruction_count - 1) * 2 : 0) + 256;

    while (pipeline_active && clock_cycles <= max_cycles) {
        writeback();
        execute();
        memory_stage();
        decode();

        if (flush_pipeline) {
            printf("--- Control hazard: pipeline flush (branch/jump taken) ---\n");
            IF_latch.is_active = false;
            IF_ID.is_active    = false;
            ID_EX.is_active    = false;
            pc             = new_pc;
            flush_pipeline = false;
        }

        fetch();

        print_cycle_report();

        pipeline_active =  IF_latch.is_active
                        || IF_ID.is_active
                        || ID_EX.is_active
                        || EX_MEM.is_active
                        || MEM_WB.is_active
                        || (pc < loaded_instruction_count);

        clock_cycles++;
    }

    printf("\n=== EXECUTION FINISHED ===\n");
    printf("Total Clock Cycles: %d\n", clock_cycles - 1);
    if (pipeline_active) {
        printf("Warning: stopped at cycle cap while pipeline still busy.\n");
    }

    print_final_registers();
    print_final_memory();

    return 0;
}
