#ifndef PARSER_H
#define PARSER_H

#include <stdbool.h>

// Reads an assembly file and loads the 32-bit packed instructions into memory
// Returns true if successful, false if the file couldn't be read.
bool load_program(const char* filename);

#endif