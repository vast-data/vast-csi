#include <p.h>

typedef struct PRing PRing;

PRing *p_ring_init(uint32_t size);
void p_ring_write(PRing *ring, uint8_t *data, uint8_t length);
void p_ring_destroy(PRing *ring);
