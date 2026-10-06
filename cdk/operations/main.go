package main

import (
	"github.com/aws/aws-cdk-go/awscdk/v2"
	"github.com/aws/jsii-runtime-go"
)

func main() {
	defer jsii.Close()

	app := awscdk.NewApp(&awscdk.AppProps{
		Outdir: jsii.String("cdk.out"),
	})
	NewOperationsStack(app, "LabOpsOperations", &OperationsStackProps{})
	app.Synth(nil)
}
