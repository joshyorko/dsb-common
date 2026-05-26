package main

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestDsbCommonReleasePlanTagsAndArtifacts(t *testing.T) {
	now := time.Date(2026, 5, 26, 17, 45, 0, 0, time.UTC)
	plan := planRelease(releasePlanInput{
		Registry:    "ghcr.io/JoshYorko",
		ImageName:   "DSB-Common",
		SHA:         "abcdef1234567890",
		RefName:     "main",
		PipelineURL: "https://github.example/actions/runs/1",
		Now:         now,
	})

	if plan.Image != "ghcr.io/joshyorko/dsb-common" {
		t.Fatalf("image = %q", plan.Image)
	}

	wantTags := []string{"latest", "20260526", "abcdef1"}
	if !reflect.DeepEqual(plan.Tags, wantTags) {
		t.Fatalf("tags = %#v, want %#v", plan.Tags, wantTags)
	}

	if plan.PrimaryRef != "ghcr.io/joshyorko/dsb-common:latest" {
		t.Fatalf("primary ref = %q", plan.PrimaryRef)
	}
	if plan.SBOMName != "dsb-common-20260526-abcdef1.spdx.json" {
		t.Fatalf("sbom name = %q", plan.SBOMName)
	}
	if plan.ProvenanceName != "dsb-common-20260526-abcdef1.provenance.json" {
		t.Fatalf("provenance name = %q", plan.ProvenanceName)
	}
	if plan.TLSVerifyArg != "--tls-verify=true" {
		t.Fatalf("tls arg = %q", plan.TLSVerifyArg)
	}
}

func TestDsbCommonReleasePlanDisablesTLSForLoopbackRegistries(t *testing.T) {
	for _, registry := range []string{"localhost", "localhost:5000", "127.0.0.1", "127.0.0.1:5000", "[::1]", "[::1]:5000"} {
		plan := planRelease(releasePlanInput{
			Registry:  registry,
			ImageName: "dsb-common",
			SHA:       "abcdef1234567890",
			Now:       time.Date(2026, 5, 26, 0, 0, 0, 0, time.UTC),
		})

		if plan.TLSVerify {
			t.Fatalf("%s: TLSVerify = true", registry)
		}
		if plan.TLSVerifyArg != "--tls-verify=false" {
			t.Fatalf("%s: TLSVerifyArg = %q", registry, plan.TLSVerifyArg)
		}
	}
}

func TestDsbCommonRepositoryPartsDeriveImageMetadataFromRef(t *testing.T) {
	registry, imageName := repositoryParts("registry.gitlab.com/group/subgroup/dsb-common@sha256:abc123")
	if registry != "registry.gitlab.com/group/subgroup" {
		t.Fatalf("registry = %q", registry)
	}
	if imageName != "dsb-common" {
		t.Fatalf("imageName = %q", imageName)
	}
}

func TestDsbCommonProvenanceIncludesPortableReleaseContext(t *testing.T) {
	plan := planRelease(releasePlanInput{
		Registry:    "registry.gitlab.com/group",
		ImageName:   "dsb-common",
		SHA:         "abcdef1234567890",
		RefName:     "release-main",
		PipelineURL: "https://gitlab.example/pipelines/42",
		SourceURI:   "https://gitlab.example/group/dsb-common",
		Now:         time.Date(2026, 5, 26, 17, 45, 0, 0, time.UTC),
	})

	predicate, err := provenancePredicate(plan)
	if err != nil {
		t.Fatalf("provenancePredicate returned error: %v", err)
	}

	var decoded map[string]any
	if err := json.Unmarshal(predicate, &decoded); err != nil {
		t.Fatalf("predicate is not json: %v", err)
	}

	body := string(predicate)
	for _, want := range []string{
		"https://slsa.dev/provenance/v1",
		"abcdef1234567890",
		"registry.gitlab.com/group/dsb-common:latest",
		"release-main",
		"https://gitlab.example/pipelines/42",
		"https://gitlab.example/group/dsb-common",
	} {
		if !strings.Contains(body, want) {
			t.Fatalf("predicate did not include %q:\n%s", want, body)
		}
	}
}
