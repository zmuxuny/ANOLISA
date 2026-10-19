//! Closing ATX markers are syntax, not part of a contract section's title.
use skillfs_core::parser::parse_skill_md;

fn document(body: &str) -> String {
    format!("---\nname: test\ndescription: Closed headings\n---\n\n{body}")
}

#[test]
fn extracts_both_contract_sections_with_closing_hashes() {
    for suffix in [" #", " ###", "\t##\t", " #######   "] {
        let content = document(&format!(
            "## Parameters{suffix}\n- `input` (string, required): Input\n## Returns{suffix}\n- `output` (string): Output\n"
        ));
        let entry = parse_skill_md(&content, "test");
        assert!(entry.parse_status.is_ok(), "{suffix:?}");
        assert_eq!(entry.parameters.len(), 1, "{suffix:?}");
        assert_eq!(entry.parameters[0].name, "input");
        assert_eq!(entry.returns.len(), 1, "{suffix:?}");
        assert_eq!(entry.returns[0].name, "output");
    }
}

#[test]
fn closing_markers_do_not_hide_duplicate_contract_sections() {
    let entry = parse_skill_md(
        &document(
            "## Parameters\n- `first` (string): First\n## Parameters ##\n- `second` (string): Second\n",
        ),
        "test",
    );
    assert!(entry.parse_status.is_degraded());
    assert_eq!(entry.parameters.len(), 2);
    assert_eq!(entry.parameters[0].name, "first");
    assert_eq!(entry.parameters[1].name, "second");
}

#[test]
fn closed_headings_work_with_crlf_and_unterminated_body() {
    let content = document("## Parameters ##\n- `input` (string): Input").replace('\n', "\r\n");
    let entry = parse_skill_md(&content, "test");
    assert!(entry.parse_status.is_ok());
    assert_eq!(entry.parameters.len(), 1);
}

#[test]
fn literal_or_escaped_hashes_remain_part_of_the_title() {
    for title in [
        "Parameters#",
        "Parameters ## text",
        "Parameters \\##",
        "Parameters # #",
        "Parameters\u{00a0}##",
        "Parameters ##\u{00a0}",
    ] {
        let content = document(&format!("## {title}\n- `example` (string): Example\n"));
        let entry = parse_skill_md(&content, "test");
        assert!(entry.parameters.is_empty(), "{title:?}");
    }
}

#[test]
fn fenced_closed_headings_do_not_create_contracts() {
    for fence in ["```", "~~~~"] {
        let content = document(&format!(
            "{fence}\n## Parameters ##\n- `example` (string): Example\n{fence}\n"
        ));
        let entry = parse_skill_md(&content, "test");
        assert!(entry.parameters.is_empty());
    }
}
