# Host unit tests for the Nuki protocol (no Zephyr, no DK needed).
# libsodium is the reference implementation: brew install libsodium
#   make        build and run
#   make clean

SRC_DIR  := ../../../src/nuki
SODIUM   := $(shell pkg-config --cflags --libs libsodium 2>/dev/null || echo -lsodium)
CFLAGS   := -std=c11 -Wall -Wextra -Werror -O1 -g -fsanitize=address,undefined -I$(SRC_DIR)

BIN  := build/test_nuki
SRCS := $(SRC_DIR)/nuki_proto.c
# TweetNaCl as published, built without the strict warnings and without UBSan: it shifts negative
# limbs left (car25519), which GCC and Clang define as two's complement arithmetic
NACL := $(SRC_DIR)/tweetnacl/tweetnacl.c

.PHONY: test clean
test: $(BIN)
	./$(BIN)

$(BIN): test_nuki.c $(SRCS) $(SRC_DIR)/nuki_proto.h $(NACL)
	@mkdir -p build
	$(CC) -O1 -g -fsanitize=address -w -c -o build/tweetnacl.o $(NACL)
	$(CC) $(CFLAGS) -o $@ test_nuki.c $(SRCS) build/tweetnacl.o $(SODIUM)

clean:
	rm -rf build
