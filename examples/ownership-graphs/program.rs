// SPDX-License-Identifier: Apache-2.0

mod provider;
use provider::*;

fn main() {
    let mut root = tree_new(65);
    let child = tree_new(66);
    tree_attach_left(&mut root, child);
    let leaf = tree_left(&root);
    let parent = tree_parent(&leaf);
    let parent_value = tree_value(&parent);
    let child_value = tree_value(&leaf);
    assert_eq!(*parent_value, 65);
    assert_eq!(*child_value, 66);
    let mut detached = tree_take_left(&mut root);
    drop(root);
    let leaf = tree_left(&detached);
    let value = tree_value(&leaf);
    assert_eq!(*value, 66);
    let replacement = tree_new(67);
    tree_attach_left(&mut detached, replacement);
    println!("OK");
}
