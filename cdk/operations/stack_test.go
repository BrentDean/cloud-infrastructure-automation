package main

import (
	"testing"

	"github.com/aws/aws-cdk-go/awscdk/v2"
	"github.com/aws/aws-cdk-go/awscdk/v2/assertions"
	"github.com/aws/jsii-runtime-go"
)

func synthTemplate(t *testing.T) assertions.Template {
	t.Helper()
	app := awscdk.NewApp(nil)
	stack := NewOperationsStack(app, "TestOperations", &OperationsStackProps{})
	return assertions.Template_FromStack(stack, nil)
}

func TestOperationsResourceCounts(t *testing.T) {
	defer jsii.Close()
	template := synthTemplate(t)

	template.ResourceCountIs(jsii.String("AWS::SNS::Topic"), jsii.Number(1))
	template.ResourceCountIs(jsii.String("AWS::CloudWatch::Alarm"), jsii.Number(5))
	template.ResourceCountIs(jsii.String("AWS::CloudWatch::Dashboard"), jsii.Number(1))
}

func TestStackConsumesTerraformInstanceIDsAsParameters(t *testing.T) {
	defer jsii.Close()
	template := synthTemplate(t)

	for _, parameter := range []string{
		"WebInstanceId",
		"AppInstanceId",
		"BrokerInstanceId",
		"DatabaseInstanceId",
	} {
		template.HasParameter(jsii.String(parameter), map[string]interface{}{
			"Type": jsii.String("AWS::EC2::Instance::Id"),
		})
	}
}

func TestStatusAndBrokerCPUAlarms(t *testing.T) {
	defer jsii.Close()
	template := synthTemplate(t)

	template.ResourcePropertiesCountIs(
		jsii.String("AWS::CloudWatch::Alarm"),
		map[string]interface{}{
			"Namespace":  jsii.String("AWS/EC2"),
			"MetricName": jsii.String("StatusCheckFailed"),
			"Threshold":  jsii.Number(1),
		},
		jsii.Number(4),
	)
	template.ResourcePropertiesCountIs(
		jsii.String("AWS::CloudWatch::Alarm"),
		map[string]interface{}{
			"Namespace":  jsii.String("AWS/EC2"),
			"MetricName": jsii.String("CPUUtilization"),
			"Threshold":  jsii.Number(85),
		},
		jsii.Number(1),
	)
}

func TestSNSTopicUsesSignatureVersionTwo(t *testing.T) {
	defer jsii.Close()
	template := synthTemplate(t)

	template.HasResourceProperties(
		jsii.String("AWS::SNS::Topic"),
		map[string]interface{}{
			"SignatureVersion": jsii.String("2"),
		},
	)
}
