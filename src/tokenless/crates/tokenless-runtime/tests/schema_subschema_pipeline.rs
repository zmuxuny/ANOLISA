//! Nested parameter descriptions use the same recovery and host-capability
//! contract as descriptions declared directly on a tool.

use std::sync::Arc;

use serde_json::{Value, json};
use tokenless_ccr::{InMemoryStore, StashStore, compute_key};
use tokenless_protocol::{
    Attribution, BeforeModelCapabilities, BeforeModelRequest, RecoveryMethod, Request,
    RequestEnvelope, Response, RetrieveRequest,
};
use tokenless_runtime::{EntryOptions, dispatch_with_store};

fn tool() -> Value {
    let parameters: Value = serde_json::from_str(include_str!(
        "../../tokenless-schema/tests/fixtures/pydantic_ranges.json"
    ))
    .unwrap();
    json!({"type": "function", "function": {"name": "select_ranges", "parameters": parameters}})
}

fn options() -> EntryOptions {
    EntryOptions {
        compression_enabled: true,
        search_path_sharing_enabled: true,
        diff_compression_enabled: false,
        html_extraction_enabled: true,
        stash_enabled: true,
        rtk_path: None,
        rtk_data_dir: None,
    }
}

fn request(tool: Value, replace_tools: bool, recovery: RecoveryMethod) -> RequestEnvelope {
    RequestEnvelope {
        attribution: Attribution::new("schema-regression"),
        request: Request::BeforeModel(BeforeModelRequest {
            tools: vec![tool],
            visible_context: json!({}),
            capabilities: BeforeModelCapabilities {
                replace_tools,
                recovery,
            },
        }),
    }
}

#[test]
fn before_model_compresses_and_recovers_pydantic_field_descriptions() {
    let original = tool();
    let store: Arc<dyn StashStore> = Arc::new(InMemoryStore::new());
    let outcome = dispatch_with_store(
        &request(
            original.clone(),
            true,
            RecoveryMethod::tool("recover").unwrap(),
        ),
        &options(),
        Some(&store),
        None,
    )
    .unwrap();
    let Response::BeforeModel(response) = outcome.response.response else {
        panic!("wrong operation")
    };
    assert_eq!(outcome.stash_writes, Some(2));
    assert_eq!(response.visible_markers.len(), 2);
    assert!(
        serde_json::to_string(&response.tools[0]).unwrap().len()
            < serde_json::to_string(&original).unwrap().len()
    );
    for field in ["start", "stop"] {
        let path = format!("/function/parameters/$defs/Range/properties/{field}");
        let before = original.pointer(&path).unwrap();
        let after = response.tools[0].pointer(&path).unwrap();
        let description = before["description"].as_str().unwrap();
        assert!(after["description"].as_str().unwrap().len() <= 160);
        assert_eq!(after["minimum"], before["minimum"]);
        assert_eq!(after["type"], before["type"]);
        let restored = dispatch_with_store(
            &RequestEnvelope {
                attribution: Attribution::new("schema-regression"),
                request: Request::Retrieve(RetrieveRequest {
                    hash_or_marker: compute_key(description.as_bytes()),
                    visible_markers: response.visible_markers.clone(),
                }),
            },
            &options(),
            Some(&store),
            None,
        )
        .unwrap();
        let Response::Retrieve(restored) = restored.response.response else {
            panic!("wrong operation")
        };
        assert_eq!(restored.payload, description);
    }
    assert_eq!(
        response.tools[0]["function"]["parameters"]["properties"]["ranges"]["items"],
        original["function"]["parameters"]["properties"]["ranges"]["items"]
    );
}

#[test]
fn nested_schema_compression_respects_host_replacement_and_recovery_gates() {
    for (replace_tools, recovery) in [
        (false, RecoveryMethod::tool("recover").unwrap()),
        (true, RecoveryMethod::None),
    ] {
        let original = tool();
        let store: Arc<dyn StashStore> = Arc::new(InMemoryStore::new());
        let outcome = dispatch_with_store(
            &request(original.clone(), replace_tools, recovery),
            &options(),
            Some(&store),
            None,
        )
        .unwrap();
        let Response::BeforeModel(response) = outcome.response.response else {
            panic!("wrong operation")
        };
        assert_eq!(response.tools, vec![original]);
        assert!(response.visible_markers.is_empty());
        assert!(outcome.artifact_keys.is_empty());
        assert_eq!(store.len(), 0);
    }
}
