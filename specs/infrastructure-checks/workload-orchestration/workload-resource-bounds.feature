@domain:infrastructure-checks @area:workload-orchestration @from:greenlint/infra
Feature: Flagging unbounded and non-elastic workloads
  Flags Kubernetes and docker-compose workloads that have no resource bounds or cannot scale down, so operators right-size hosts and stop idling at peak capacity.

  Background:
    Given a project containing YAML manifests

  @id:infrastructure-checks.workload-orchestration.001 @rule:infra.kubernetes.workload-needs-resources @verified @source:greenlint/infra.py#_k8s_resources_findings @test:tests/test_greenlint.py#test_detects_k8s_deployment_without_resources @test:tests/test_greenlint.py#test_k8s_deployment_with_resources_not_flagged @questionable
  Scenario Outline: A Kubernetes workload with no resource requests or limits is flagged
    Given a YAML manifest of kind <kind> that <resources>
    When the developer scans the project
    Then the scan reports <outcome>

    Examples:
      | kind        | resources                       | outcome                                                                            |
      | Deployment  | has no resources: block         | GL014 "Kubernetes workload without CPU/memory requests or limits" on the kind line |
      | StatefulSet | has no resources: block         | GL014 on the kind line                                                             |
      | DaemonSet   | has no resources: block         | GL014 on the kind line                                                             |
      | Pod         | has no resources: block         | GL014 on the kind line                                                             |
      | Deployment  | sets resources.limits.cpu: 500m | no GL014 finding                                                                   |
      | CronJob     | has no resources: block         | no GL014 finding                                                                   |

  @id:infrastructure-checks.workload-orchestration.002 @rule:infra.kubernetes.helm-templates-not-judged @verified @source:greenlint/infra.py#_k8s_resources_findings @test:tests/test_greenlint.py#test_helm_template_not_flagged_for_missing_resources
  Scenario: Unrendered Helm templates are not flagged for missing resources
    Given a Deployment manifest whose pod spec comes from a template include such as {{- include "app.podSpec" . | nindent 4 }}
    And the manifest has no resources: block
    When the developer scans the project
    Then the scan reports no GL014 finding

  @id:infrastructure-checks.workload-orchestration.003 @rule:infra.kubernetes.hpa-must-be-elastic @verified @source:greenlint/infra.py#_k8s_hpa_static_findings @test:tests/test_greenlint.py#test_detects_fixed_range_hpa @test:tests/test_greenlint.py#test_elastic_hpa_not_flagged
  Scenario Outline: A HorizontalPodAutoscaler whose minimum and maximum replicas are equal is flagged
    Given a HorizontalPodAutoscaler manifest with minReplicas: <min> and maxReplicas: <max>
    When the developer scans the project
    Then the scan reports <outcome>

    Examples:
      | min | max | outcome                                                                                 |
      | 3   | 3   | GL033 "HorizontalPodAutoscaler with minReplicas == maxReplicas" on the minReplicas line |
      | 1   | 5   | no GL033 finding                                                                        |

  @id:infrastructure-checks.workload-orchestration.004 @rule:infra.compose.services-need-limits @verified @source:greenlint/infra.py#_compose_resources_findings @test:tests/test_greenlint.py#test_detects_compose_service_without_limits @test:tests/test_greenlint.py#test_compose_service_with_mem_limit_not_flagged
  Scenario Outline: A compose file with no resource limit anywhere is flagged
    Given a docker-compose file with a top-level services: key whose web service <limits>
    When the developer scans the project
    Then the scan reports <outcome>

    Examples:
      | limits                                    | outcome                                                                         |
      | sets only image: nginx                    | GL034 "docker-compose service(s) without resource limits" on the services: line |
      | sets mem_limit: 512m                      | no GL034 finding                                                                |
      | sets deploy.resources.limits.memory: 512M | no GL034 finding                                                                |
      | sets cpus: 0.5                            | no GL034 finding                                                                |
