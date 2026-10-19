//! Numeric fidelity checks shared by compression and observability.

/// Whether number literals in valid JSON keep their exact decimal values when
/// parsed and serialized by `serde_json`.
///
/// Callers must validate JSON syntax first. This checks numeric fidelity only;
/// it skips quoted strings and accepts equivalent exponent/decimal spellings.
#[must_use]
pub fn json_numbers_are_exact(input: &str) -> bool {
    let bytes = input.as_bytes();
    let mut index = 0;
    while index < bytes.len() {
        match bytes[index] {
            b'"' => {
                index += 1;
                while index < bytes.len() {
                    match bytes[index] {
                        b'\\' => index += 2,
                        b'"' => {
                            index += 1;
                            break;
                        }
                        _ => index += 1,
                    }
                }
            }
            b'-' | b'0'..=b'9' => {
                let start = index;
                while index < bytes.len()
                    && matches!(bytes[index], b'0'..=b'9' | b'-' | b'+' | b'.' | b'e' | b'E')
                {
                    index += 1;
                }
                let literal = &input[start..index];
                let Ok(number) = serde_json::from_str::<serde_json::Number>(literal) else {
                    return false;
                };
                let Some(expected) = decimal_value(literal) else {
                    return false;
                };
                if decimal_value(&number.to_string()).as_ref() != Some(&expected) {
                    return false;
                }
            }
            _ => index += 1,
        }
    }
    true
}

// Compare decimal values without floating-point conversion. Equivalent JSON
// spellings (1e3, 1000.0) share a sign, zero-stripped coefficient and exponent.
fn decimal_value(literal: &str) -> Option<(bool, String, i64)> {
    let (negative, literal) = match literal.strip_prefix('-') {
        Some(literal) => (true, literal),
        None => (false, literal),
    };
    let (mantissa, exponent) = match literal.split_once(['e', 'E']) {
        Some((mantissa, exponent)) => (mantissa, exponent.parse::<i64>().ok()?),
        None => (literal, 0),
    };
    let fractional = mantissa
        .split_once('.')
        .map_or(0, |(_, fractional)| fractional.len());
    let digits: String = mantissa.chars().filter(char::is_ascii_digit).collect();
    let digits = digits.trim_start_matches('0');
    if digits.is_empty() {
        return Some((negative, String::new(), 0));
    }
    let coefficient = digits.trim_end_matches('0');
    let trailing = i64::try_from(digits.len() - coefficient.len()).ok()?;
    let exponent = exponent
        .checked_sub(i64::try_from(fractional).ok()?)?
        .checked_add(trailing)?;
    Some((negative, coefficient.to_owned(), exponent))
}
