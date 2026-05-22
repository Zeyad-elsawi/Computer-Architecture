#ifndef CPU_H
#define CPU_H

#include <stdbool.h>

typedef struct {
    bool is_active;
    int  instruction;
    int  pc;
    int  cycles_in_stage;

    int opcode;
    int r1, r2, r3;
    int shamt;
    int imm;
    int address;

    int valR1;
    int valR2;

    int alu_result;
    int mem_data;
} PipelineRegister;

extern int memory[2048];
extern bool data_memory_modified[2048]; /* set when SW updates data memory */
extern int registers[32];
extern int pc;
extern int loaded_instruction_count;
extern int clock_cycles;

extern bool flush_pipeline;
extern int  new_pc;
extern bool mem_active_this_cycle;  /* true when data memory bus used (LW/SW) */
extern bool mem_stage_this_cycle;   /* true when MEM stage processed EX_MEM */
extern bool fetched_this_cycle;     /* true when instruction memory was read */

/* Five separate latches */
extern PipelineRegister IF_latch;   /* IF stage  (1 cycle)  */
extern PipelineRegister IF_ID;      /* ID stage  (2 cycles) */
extern PipelineRegister ID_EX;      /* EX stage  (2 cycles) */
extern PipelineRegister EX_MEM;     /* MEM stage (1 cycle)  */
extern PipelineRegister MEM_WB;     /* WB stage  (1 cycle)  */

void fetch();
void decode();
void execute();
void memory_stage();
void writeback();

#endif