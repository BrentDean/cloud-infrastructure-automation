package main

import (
	"testing"

	"github.com/aws/aws-cdk-go/awscdk/v2"
	"github.com/aws/aws-cdk-go/awscdk/v2/assertions"
	"github.com/aws/jsii-runtime-go"
)

func templateForTest() assertions.Template {
	app := awscdk.NewApp(nil)
	stack := NewOperationsMonitoringStack(app, "TestStack", nil)
	return assertions.Template_FromStack(stack, nil)
}

func TestCreatesFourEC2StatusAlarms(t *testing.T) {
	template := templateForTest()
	template.ResourceCountIs(jsii.String("AWS::CloudWatch::Alarm"), jsii.Number(4))
	template.HasResourceProperties(
		jsii.String("AWS::CloudWatch::Alarm"),
		map[string]interface{}{
			"MetricName":        "StatusCheckFailed",
			"Namespace":         "AWS/EC2",
			"Statistic":         "Maximum",
			"Threshold":         1,
			"EvaluationPeriods": 2,
			"DatapointsToAlarm": 2,
			"TreatMissingData":  "notBreaching",
		},
	)
}

func TestCreatesEncryptedSNSTopicAndDashboard(t *testing.T) {
	template := templateForTest()
	template.ResourceCountIs(jsii.String("AWS::SNS::Topic"), jsii.Number(1))
	template.HasResourceProperties(
		jsii.String("AWS::SNS::Topic"),
		map[string]interface{}{
			"DisplayName":    "LabOps operations alerts",
			"KmsMasterKeyId": assertions.Match_AnyValue(),
		},
	)
	template.ResourceCountIs(jsii.String("AWS::CloudWatch::Dashboard"), jsii.Number(1))
}

func TestRequiresTerraformCreatedInstanceIDs(t *testing.T) {
	template := templateForTest()
	templateJSON := *template.ToJSON()
	parameters, ok := templateJSON["Parameters"].(map[string]interface{})
	if !ok {
		t.Fatal("synthesized template has no Parameters section")
	}
	for _, role := range monitoredRoles {
		id := parameterID(role)
		if _, exists := parameters[id]; !exists {
			t.Fatalf("missing CloudFormation parameter %s", id)
		}
	}
}
