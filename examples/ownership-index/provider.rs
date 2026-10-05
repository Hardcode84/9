// SPDX-License-Identifier: Apache-2.0

use std::cell::Cell;
use std::ptr;

struct Symbol {
    next: *mut Symbol,
    key: i64,
    value: i64,
}
struct Alias {
    next: Option<Box<Alias>>,
    target: Cell<*const Symbol>,
    key: i64,
}
pub struct Index {
    symbols: *mut Symbol,
    aliases: Option<Box<Alias>>,
}
pub struct Selection<'a> {
    target: Option<&'a i64>,
}

pub fn index_new() -> Index {
    Index {
        symbols: ptr::null_mut(),
        aliases: None,
    }
}

fn symbol_find(index: &Index, key: i64) -> *const Symbol {
    let mut node = index.symbols;
    // Symbol addresses remain fixed until index_remove or Index::drop.
    unsafe {
        while !node.is_null() {
            if (*node).key == key {
                return node;
            }
            node = (*node).next;
        }
    }
    ptr::null()
}

fn alias_find(index: &Index, key: i64) -> Option<&Alias> {
    let mut node = index.aliases.as_deref();
    while let Some(alias) = node {
        if alias.key == key {
            return Some(alias);
        }
        node = alias.next.as_deref();
    }
    None
}

pub fn index_insert(index: &mut Index, key: i64, value: i64) {
    assert!(symbol_find(index, key).is_null());
    index.symbols = Box::into_raw(Box::new(Symbol {
        next: index.symbols,
        key,
        value,
    }));
}

pub fn index_alias(index: &mut Index, key: i64, target: i64) {
    assert!(alias_find(index, key).is_none());
    let target = Cell::new(symbol_find(index, target));
    index.aliases = Some(Box::new(Alias {
        next: index.aliases.take(),
        target,
        key,
    }));
}

pub fn index_bind(index: &Index, key: i64, target: i64) -> bool {
    let Some(alias) = alias_find(index, key) else {
        return false;
    };
    alias.target.set(symbol_find(index, target));
    true
}

pub fn index_remove(index: &mut Index, key: i64) -> bool {
    let target = symbol_find(index, key);
    if target.is_null() {
        return false;
    }
    let mut alias = index.aliases.as_deref();
    while let Some(entry) = alias {
        if entry.target.get() == target {
            entry.target.set(ptr::null());
        }
        alias = entry.next.as_deref();
    }
    let mut link: *mut *mut Symbol = &mut index.symbols;
    // All incoming aliases are clear. Exclusive access excludes selections.
    unsafe {
        while (**link).key != key {
            link = &raw mut (**link).next;
        }
        let removed = *link;
        *link = (*removed).next;
        drop(Box::from_raw(removed));
    }
    true
}

pub fn index_select(index: &Index, key: i64) -> Selection<'_> {
    let pointer = alias_find(index, key).map_or(ptr::null(), |alias| alias.target.get());
    // Only index_remove retires targets; it unbinds aliases and needs &mut Index.
    // Rebinding changes a Cell, not a symbol. A selection retains the index loan.
    let target = unsafe { pointer.as_ref().map(|symbol| &symbol.value) };
    Selection { target }
}

pub fn selection_present(selection: &Selection<'_>) -> bool {
    selection.target.is_some()
}
pub fn selection_value<'a>(selection: &Selection<'a>) -> &'a i64 {
    selection.target.unwrap()
}

impl Drop for Index {
    fn drop(&mut self) {
        while let Some(mut alias) = self.aliases.take() {
            self.aliases = alias.next.take();
        }
        // No selection can outlive its Index. Each allocation is released once.
        unsafe {
            while !self.symbols.is_null() {
                let node = self.symbols;
                self.symbols = (*node).next;
                drop(Box::from_raw(node));
            }
        }
    }
}
