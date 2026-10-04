/* SPDX-License-Identifier: Apache-2.0 */

#include "crust0_host.h"

#include <stddef.h>
#include <stdint.h>

typedef struct Hook Hook;
struct Hook {
    Hook *prev;
    Hook *next;
};

typedef struct {
    uint64_t value[2];
    Hook hook;
} Node;

typedef struct {
    Node node;
    char byte;
} NodeAlignment;

static void init(Hook *h)
{
    h->prev = h;
    h->next = h;
}

static void insert_after(Hook *at, Hook *h)
{
    Hook *next = at->next;
    h->prev = at;
    h->next = next;
    next->prev = h;
    at->next = h;
}

static void unlink_node(Hook *h)
{
    Hook *before = h->prev;
    Hook *after = h->next;
    before->next = after;
    after->prev = before;
    init(h);
}

static Node *node_of(Hook *h) { return (Node *)((unsigned char *)h - offsetof(Node, hook)); }

int main(int argc, char **argv)
{
    Hook head;
    Node *first;
    Node *second;
    Node *found;
    (void)argc;
    (void)argv;
    if (offsetof(Node, hook) == 0) {
        return 9;
    }
    init(&head);
    first = crust0_host_alloc(sizeof(Node), sizeof(NodeAlignment) - sizeof(Node));
    if (first == NULL) {
        return 1;
    }
    second = crust0_host_alloc(sizeof(Node), sizeof(NodeAlignment) - sizeof(Node));
    if (second == NULL) {
        crust0_host_free(first);
        return 2;
    }
    first->value[0] = 11;
    first->value[1] = 111;
    second->value[0] = 22;
    second->value[1] = 222;
    init(&first->hook);
    init(&second->hook);
    insert_after(&head, &first->hook);
    insert_after(&first->hook, &second->hook);
    unlink_node(&first->hook);
    crust0_host_free(first);
    found = node_of(head.next);
    if (found != second || found->value[0] != 22 || found->value[1] != 222) {
        return 3;
    }
    if (head.prev != &second->hook || second->hook.prev != &head) {
        return 4;
    }
    first = crust0_host_alloc(sizeof(Node), sizeof(NodeAlignment) - sizeof(Node));
    if (first == NULL) {
        unlink_node(&second->hook);
        crust0_host_free(second);
        return 5;
    }
    first->value[0] = 33;
    first->value[1] = 333;
    init(&first->hook);
    insert_after(&head, &first->hook);
    unlink_node(&second->hook);
    crust0_host_free(second);
    found = node_of(head.next);
    if (found != first || found->value[0] != 33 || found->value[1] != 333 ||
        head.prev != &first->hook) {
        return 6;
    }
    unlink_node(&first->hook);
    crust0_host_free(first);
    if (head.next != &head || head.prev != &head) {
        return 7;
    }
    if (crust0_host_write_stream(1, (const unsigned char *)"intrusive: ok\n", 14) != 0) {
        return 8;
    }
    return 0;
}
