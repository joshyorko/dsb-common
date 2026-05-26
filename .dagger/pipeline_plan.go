package main

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

const (
	defaultImageName    = "dsb-common"
	defaultRegistry     = "ghcr.io/joshyorko"
	defaultBuildahImage = "quay.io/buildah/stable:v1.41"
	defaultTrivyImage   = "aquasec/trivy:latest"
	defaultCosignImage  = "gcr.io/projectsigstore/cosign:latest"
)

type releasePlanInput struct {
	Registry    string
	ImageName   string
	SHA         string
	RefName     string
	PipelineURL string
	SourceURI   string
	Now         time.Time
}

type ReleasePlan struct {
	Image          string
	PrimaryRef     string
	TagRefs        []string
	Tags           []string
	SHA            string
	ShortSHA       string
	Date           string
	Created        string
	RefName        string
	PipelineURL    string
	SourceURI      string
	SBOMName       string
	ProvenanceName string
	TLSVerify      bool
	TLSVerifyArg   string
}

type ReleaseSummary struct {
	Image                string
	PrimaryRef           string
	DigestRefs           []string
	Tags                 []string
	SBOMName             string
	ProvenanceName       string
	Published            bool
	PublishSkippedReason string
	SBOMGenerated        bool
	SBOMSkippedReason    string
	Signed               bool
	SignSkippedReason    string
	Attested             bool
	AttestSkippedReason  string
	BuildLog             string
}

func planRelease(input releasePlanInput) *ReleasePlan {
	now := input.Now.UTC()
	if now.IsZero() {
		now = time.Now().UTC()
	}

	registry := lowerDefault(input.Registry, defaultRegistry)
	imageName := lowerDefault(input.ImageName, defaultImageName)
	sha := strings.TrimSpace(input.SHA)
	shortSHA := sha
	if len(shortSHA) > 7 {
		shortSHA = shortSHA[:7]
	}

	date := now.Format("20060102")
	image := fmt.Sprintf("%s/%s", registry, imageName)
	tags := []string{"latest", date, shortSHA}

	plan := &ReleasePlan{
		Image:          image,
		Tags:           tags,
		SHA:            sha,
		ShortSHA:       shortSHA,
		Date:           date,
		Created:        now.Format(time.RFC3339),
		RefName:        input.RefName,
		PipelineURL:    input.PipelineURL,
		SourceURI:      defaultString(input.SourceURI, "local-source"),
		SBOMName:       fmt.Sprintf("%s-%s-%s.spdx.json", imageName, date, shortSHA),
		ProvenanceName: fmt.Sprintf("%s-%s-%s.provenance.json", imageName, date, shortSHA),
		TLSVerify:      tlsVerify(image),
		TLSVerifyArg:   tlsVerifyArg(image),
	}
	for _, tag := range tags {
		ref := fmt.Sprintf("%s:%s", image, tag)
		plan.TagRefs = append(plan.TagRefs, ref)
	}
	plan.PrimaryRef = plan.TagRefs[0]

	return plan
}

func provenancePredicate(plan *ReleasePlan) ([]byte, error) {
	predicate := map[string]any{
		"_type": "https://slsa.dev/provenance/v1",
		"buildDefinition": map[string]any{
			"buildType": "https://dagger.io/dudley/release-pipeline/v1",
			"externalParameters": map[string]any{
				"image":        plan.Image,
				"tags":         plan.Tags,
				"tagRefs":      plan.TagRefs,
				"sha":          plan.SHA,
				"refName":      plan.RefName,
				"pipelineURL":  plan.PipelineURL,
				"tlsVerify":    plan.TLSVerify,
				"sbom":         plan.SBOMName,
				"provenance":   plan.ProvenanceName,
				"imageFormat":  "oci",
				"buildTool":    "buildah",
				"sbomTool":     "trivy",
				"signingTool":  "cosign",
				"defaultImage": defaultImageName,
			},
			"internalParameters": map[string]any{},
			"resolvedDependencies": []map[string]any{
				{
					"uri": plan.SourceURI,
					"digest": map[string]string{
						"gitCommit": plan.SHA,
					},
				},
			},
		},
		"runDetails": map[string]any{
			"builder": map[string]any{
				"id": "dagger://dsb-common/release",
			},
			"metadata": map[string]any{
				"invocationID": plan.PipelineURL,
				"startedOn":    plan.Created,
				"finishedOn":   plan.Created,
			},
		},
	}

	return json.MarshalIndent(predicate, "", "  ")
}

func summaryFromPlan(plan *ReleasePlan) *ReleaseSummary {
	return &ReleaseSummary{
		Image:          plan.Image,
		PrimaryRef:     plan.PrimaryRef,
		Tags:           append([]string{}, plan.Tags...),
		SBOMName:       plan.SBOMName,
		ProvenanceName: plan.ProvenanceName,
	}
}

func lowerDefault(value, fallback string) string {
	return strings.ToLower(defaultString(value, fallback))
}

func defaultString(value, fallback string) string {
	if strings.TrimSpace(value) == "" {
		return fallback
	}
	return strings.TrimSpace(value)
}

func registryHost(image string) string {
	host, _, ok := strings.Cut(image, "/")
	if !ok {
		return image
	}
	return host
}

func tlsVerify(image string) bool {
	host := registryHost(image)
	return !(host == "localhost" || strings.HasPrefix(host, "localhost:") || host == "127.0.0.1" || strings.HasPrefix(host, "127.0.0.1:") || host == "[::1]" || strings.HasPrefix(host, "[::1]:"))
}

func tlsVerifyArg(image string) string {
	if tlsVerify(image) {
		return "--tls-verify=true"
	}
	return "--tls-verify=false"
}

func imageRepository(imageRef string) string {
	repository := imageRef
	if before, _, ok := strings.Cut(repository, "@"); ok {
		repository = before
	}
	lastSlash := strings.LastIndex(repository, "/")
	lastColon := strings.LastIndex(repository, ":")
	if lastColon > lastSlash {
		repository = repository[:lastColon]
	}
	return repository
}

func repositoryParts(imageRef string) (string, string) {
	repository := imageRepository(imageRef)
	lastSlash := strings.LastIndex(repository, "/")
	if lastSlash < 0 {
		return defaultRegistry, repository
	}
	return repository[:lastSlash], repository[lastSlash+1:]
}
