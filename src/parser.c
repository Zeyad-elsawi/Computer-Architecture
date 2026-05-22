#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdbool.h>
#include "cpu.h" // We need this to access the global 'memory' array
#include "parser.h"

int loaded_instruction_count = 0;

// Helper function to extract the integer from "R1", "R2", etc.
int parse_reg(char* reg_str) {
    if (reg_str == NULL) return 0;
    // Skip the 'R' or 'r' and parse the number
    if (reg_str[0] == 'R' || reg_str[0] == 'r') {
        return atoi(&reg_str[1]);
    }
    return atoi(reg_str);
}

bool load_program(const char* filename) {
    FILE* file = fopen(filename, "r");
    if (file == NULL) {
        printf("Error: Could not open file %s\n", filename);
        return false;
    }

    char line[256];
    int instruction_index = 0;

    printf("--- Parsing Program ---\n");

    while (fgets(line, sizeof(line), file)) {
        // Skip empty lines or comments
        if (line[0] == '\n' || line[0] == '\r' || line[0] == '#') continue;

        char mnemonic[10];
        char op1[10], op2[10], op3[10];
        int opcode = 0, r1 = 0, r2 = 0, r3 = 0, imm_or_shamt = 0, address = 0;
        int packed_instruction = 0;

        // Read the first word (the mnemonic like ADD, ADDI, J)
        sscanf(line, "%s", mnemonic);

        // --- R-FORMAT INSTRUCTIONS ---
        if (strcmp(mnemonic, "ADD") == 0 || strcmp(mnemonic, "SUB") == 0) {
            sscanf(line, "%s %s %s %s", mnemonic, op1, op2, op3);
            opcode = (strcmp(mnemonic, "ADD") == 0) ? 0 : 1;
            r1 = parse_reg(op1);
            r2 = parse_reg(op2);
            r3 = parse_reg(op3);
            
            // Pack: OPCODE (4) | R1 (5) | R2 (5) | R3 (5) | SHAMT (13)
            packed_instruction = (opcode << 28) | (r1 << 23) | (r2 << 18) | (r3 << 13);
        }
        else if (strcmp(mnemonic, "SLL") == 0 || strcmp(mnemonic, "SRL") == 0) {
            sscanf(line, "%s %s %s %d", mnemonic, op1, op2, &imm_or_shamt);
            opcode = (strcmp(mnemonic, "SLL") == 0) ? 8 : 9;
            r1 = parse_reg(op1);
            r2 = parse_reg(op2);
            r3 = 0; // The project specifies R3 is 0 for shift instructions [cite: 62]
            
            packed_instruction = (opcode << 28) | (r1 << 23) | (r2 << 18) | (r3 << 13) | (imm_or_shamt & 0x1FFF);
        }
        // --- J-FORMAT INSTRUCTIONS ---
        else if (strcmp(mnemonic, "J") == 0) {
            sscanf(line, "%s %d", mnemonic, &address);
            opcode = 7;
            
            // Pack: OPCODE (4) | ADDRESS (28)
            packed_instruction = (opcode << 28) | (address & 0xFFFFFFF);
        }
        // --- I-FORMAT INSTRUCTIONS ---
        else {
            // MULI, ADDI, BNE, ANDI, XORI, LW, SW
            sscanf(line, "%s %s %s %d", mnemonic, op1, op2, &imm_or_shamt);
            
            if (strcmp(mnemonic, "MULI") == 0) opcode = 2;
            else if (strcmp(mnemonic, "ADDI") == 0) opcode = 3;
            else if (strcmp(mnemonic, "BNE") == 0) opcode = 4;
            else if (strcmp(mnemonic, "ANDI") == 0) opcode = 5;
            else if (strcmp(mnemonic, "XORI") == 0) opcode = 6;
            else if (strcmp(mnemonic, "LW") == 0) opcode = 10;
            else if (strcmp(mnemonic, "SW") == 0) opcode = 11;

            r1 = parse_reg(op1);
            r2 = parse_reg(op2);

            // Pack: OPCODE (4) | R1 (5) | R2 (5) | IMMEDIATE (18)
            // The bitwise & 0x3FFFF ensures negative immediates don't overwrite the registers/opcode
            packed_instruction = (opcode << 28) | (r1 << 23) | (r2 << 18) | (imm_or_shamt & 0x3FFFF);
        }

        // Store into instruction memory
        memory[instruction_index] = packed_instruction;
        printf("Loaded Memory[%d]: %s -> 0x%08X\n", instruction_index, mnemonic, packed_instruction);
        instruction_index++;
    }

    loaded_instruction_count = instruction_index;

    fclose(file);
    printf("-------------------------\n\n");
    return true;
}