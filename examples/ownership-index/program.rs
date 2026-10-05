// SPDX-License-Identifier: Apache-2.0

mod provider;
use provider::*;

struct Comparison<'a, 'b> {
    actual: &'a i64,
    expected: &'b i64,
}

fn comparison_equal(pair: &Comparison<'_, '_>) -> bool {
    pair.actual == pair.expected
}

fn expect_alias(index: &Index, key: i64, expected: &i64) {
    let selection = index_select(index, key);
    let present = selection_present(&selection);
    assert!(present);
    let value = selection_value(&selection);
    let pair = Comparison {
        actual: value,
        expected,
    };
    let equal = comparison_equal(&pair);
    assert!(equal);
}

fn expect_unbound(index: &Index, key: i64) {
    let selection = index_select(index, key);
    let present = selection_present(&selection);
    assert!(!present);
}

fn remove_required(index: &mut Index, key: i64) {
    let removed = index_remove(index, key);
    assert!(removed);
}

fn main() {
    {
        let mut index = index_new();
        index_insert(&mut index, 1, 41);
        index_insert(&mut index, 2, 42);
        index_alias(&mut index, 10, 1);
        index_alias(&mut index, 11, 1);
        index_alias(&mut index, 20, 2);
        let mut expected = 41;
        expect_alias(&index, 10, &expected);
        expect_alias(&index, 11, &expected);
        remove_required(&mut index, 1);
        expected = 42;
        expect_unbound(&index, 10);
        expect_unbound(&index, 11);
        expect_alias(&index, 20, &expected);
        index_insert(&mut index, 1, 43);
        expect_unbound(&index, 10);
        expect_unbound(&index, 11);
        let old = index_select(&index, 20);
        let bound = index_bind(&index, 20, 1);
        assert!(bound);
        let value = selection_value(&old);
        assert_eq!(*value, 42);
        expected = 43;
        expect_alias(&index, 20, &expected);
        remove_required(&mut index, 2);
        expect_alias(&index, 20, &expected);
        remove_required(&mut index, 1);
        let removed = index_remove(&mut index, 1);
        assert!(!removed);
        expect_unbound(&index, 20);
        let mut key = 0;
        let count = std::env::args_os().count() as i64 + 16;
        while key < count {
            index_insert(&mut index, key, key);
            index_alias(&mut index, key + 100, key);
            key += 1;
        }
        expected = count - 1;
        expect_alias(&index, count + 99, &expected);
    }
    println!("OK");
}
