/// <reference path="./.sst/platform/config.d.ts" />
// What it does: AWS infra for one Operator stage (develop|demo|production), values from
//   stages/<stage>/stage.yaml. Per stage: DynamoDB table, ECR repo, one EC2 server (t4g, AL2023 arm64,
//   public IP for outbound only) with an IAM role, API Gateway HTTP API → VPC Link → Cloud Map → the
//   server's port 8000, and the stage's domain in Cloudflare (DNS only). Names follow common/stage.py:
//   operator-<stage>, SSM /handyagent/operator/<stage>/...
// When it runs: `sst deploy|remove --stage <stage>`, from stages/<stage>/init.sh / remove.sh via ops.py.
// What calls it: common/aws.py (init, remove).
const AWS_STAGES = ["develop", "demo", "production"];
const REGION = "us-east-1";
const AZ = "us-east-1a";
const PORT = 8000;
// Tags: only the sst: namespace (Roman, 2026-10-03). SST adds sst:app + sst:stage itself; we add sst:project.
// Find: Resource Groups → Tag Editor; costs: Billing. Same set as common/stage.py (Stage.tags).
const PROJECT_TAG = { "sst:project": "handyagent" };

export default $config({
  app(input) {
    return {
      name: "operator",
      removal: input?.stage === "production" ? "retain" : "remove",
      protect: input?.stage === "production",
      home: "aws",
      providers: { aws: { region: REGION, defaultTags: { tags: PROJECT_TAG } }, cloudflare: true },
    };
  },
  async run() {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const YAML = await import("yaml");

    const stage = $app.stage;
    if (!AWS_STAGES.includes(stage)) {
      throw new Error(`stage must be one of ${AWS_STAGES.join("|")} (local runs in Docker, not SST)`);
    }
    const isProd = stage === "production";
    const root = process.cwd();
    const cfg = YAML.parse(fs.readFileSync(path.join(root, "stages", stage, "stage.yaml"), "utf8"));
    const name = `operator-${stage}`;
    const account = aws.getCallerIdentityOutput().accountId;

    // --- Data + image registry
    const table = new aws.dynamodb.Table("Table", {
      name,
      hashKey: "pk",
      rangeKey: "sk",
      attributes: [
        { name: "pk", type: "S" },
        { name: "sk", type: "S" },
      ],
      billingMode: "PAY_PER_REQUEST",
      pointInTimeRecovery: { enabled: Boolean(cfg.backups) },
      deletionProtectionEnabled: isProd,
    });

    const repo = new aws.ecr.Repository("Repo", { name, forceDelete: !isProd });
    new aws.ecr.LifecyclePolicy("RepoLifecycle", {
      repository: repo.name,
      policy: JSON.stringify({
        rules: [{
          rulePriority: 1,
          description: "keep the last 10 images",
          selection: { tagStatus: "any", countType: "imageCountMoreThan", countNumber: 10 },
          action: { type: "expire" },
        }],
      }),
    });

    // --- Network: the default VPC (no NAT, no extra cost)
    const vpc = aws.ec2.getVpcOutput({ default: true });
    // VPC Link subnets: API Gateway VPC Links aren't available in zone use1-az3 (failed first init).
    const subnets = aws.ec2.getSubnetsOutput({
      filters: [
        { name: "vpc-id", values: [vpc.id] },
        { name: "default-for-az", values: ["true"] },
        { name: "availability-zone-id", values: ["use1-az1", "use1-az2", "use1-az4", "use1-az5", "use1-az6"] },
      ],
    });
    const serverSubnet = aws.ec2.getSubnetOutput({ vpcId: vpc.id, availabilityZone: AZ, defaultForAz: true });

    const linkSg = new aws.ec2.SecurityGroup("LinkSg", {
      name: `${name}-vpclink`,
      vpcId: vpc.id,
      egress: [{ protocol: "-1", fromPort: 0, toPort: 0, cidrBlocks: ["0.0.0.0/0"] }],
    });
    // Inbound: only API Gateway's VPC Link, only the app port. Outbound: anywhere (Claude, Thumbtack, Telegram).
    const serverSg = new aws.ec2.SecurityGroup("ServerSg", {
      name: `${name}-server`,
      vpcId: vpc.id,
      ingress: [{ protocol: "tcp", fromPort: PORT, toPort: PORT, securityGroups: [linkSg.id] }],
      egress: [{ protocol: "-1", fromPort: 0, toPort: 0, cidrBlocks: ["0.0.0.0/0"] }],
    });

    // --- Server role
    const role = new aws.iam.Role("ServerRole", {
      name: `${name}-server`,
      assumeRolePolicy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [{ Effect: "Allow", Principal: { Service: "ec2.amazonaws.com" }, Action: "sts:AssumeRole" }],
      }),
    });
    new aws.iam.RolePolicyAttachment("ServerSsmCore", {
      role: role.name,
      policyArn: "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
    });
    new aws.iam.RolePolicyAttachment("ServerEcrRead", {
      role: role.name,
      policyArn: "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
    });
    new aws.iam.RolePolicy("ServerPolicy", {
      role: role.id,
      policy: $jsonStringify({
        Version: "2012-10-17",
        Statement: [
          { Effect: "Allow", Action: ["dynamodb:*Item", "dynamodb:Query", "dynamodb:Scan", "dynamodb:Batch*",
              "dynamodb:DescribeTable"], Resource: [table.arn, $interpolate`${table.arn}/index/*`] },
          { Effect: "Allow", Action: ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
            Resource: $interpolate`arn:aws:ssm:${REGION}:${account}:parameter/handyagent/operator/${stage}/*` },
          { Effect: "Allow", Action: "kms:Decrypt", Resource: "*",
            Condition: { StringEquals: { "kms:ViaService": `ssm.${REGION}.amazonaws.com` } } },
          // Claude Platform on AWS (REQUIREMENTS "Claude auth"). TODO verify the exact actions when it's set up.
          { Effect: "Allow", Action: "aws-external-anthropic:*", Resource: "*" },
        ],
      }),
    });
    const profile = new aws.iam.InstanceProfile("ServerProfile", { name: `${name}-server`, role: role.name });

    // --- Server
    const userData = repo.repositoryUrl.apply((repoUrl) =>
      fs.readFileSync(path.join(root, "common", "server", "user-data.sh"), "utf8")
        .replace("__START_SCRIPT__", fs.readFileSync(path.join(root, "common", "server", "operator-start.sh"), "utf8").trimEnd())
        .replace("__SERVICE_UNIT__", fs.readFileSync(path.join(root, "common", "server", "operator.service"), "utf8").trimEnd())
        .replaceAll("__STAGE__", stage)
        .replaceAll("__REGION__", REGION)
        .replaceAll("__ECR_REPO_URL__", repoUrl),
    );
    const ami = aws.ssm.getParameterOutput({
      name: "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64",
    }).value;
    const server = new aws.ec2.Instance("Server", {
      ami,
      instanceType: cfg.instance_type,
      subnetId: serverSubnet.id,
      vpcSecurityGroupIds: [serverSg.id],
      iamInstanceProfile: profile.name,
      associatePublicIpAddress: true, // outbound only; inbound is closed by ServerSg
      userData,
      userDataReplaceOnChange: true,
      rootBlockDevice: { volumeSize: 20, volumeType: "gp3", tags: { ...PROJECT_TAG, "sst:app": "operator", "sst:stage": stage } }, // tags skip the disk
      metadataOptions: { httpTokens: "required" },
      tags: { Name: `handyagent-${name}` }, // console display name; deploy finds the server by it (common/stage.py)
    }, { ignoreChanges: ["ami"] }); // a newer AMI must not replace the server; replace on purpose only

    // --- Cloud Map: API Gateway finds the server's private IP here
    const namespace = new aws.servicediscovery.HttpNamespace("Namespace", { name });
    const service = new aws.servicediscovery.Service("Service", { name: "operator", namespaceId: namespace.id });
    new aws.servicediscovery.Instance("ServiceInstance", {
      instanceId: "server",
      serviceId: service.id,
      attributes: { AWS_INSTANCE_IPV4: server.privateIp, AWS_INSTANCE_PORT: String(PORT) },
    });

    // --- API Gateway (HTTP API) → VPC Link → Cloud Map → server:8000, on the stage's domain
    const api = new sst.aws.ApiGatewayV2("Api", {
      vpc: { securityGroups: [linkSg.id], subnets: subnets.ids },
      domain: { name: cfg.domain, dns: sst.cloudflare.dns() },
      transform: {
        stage: { defaultRouteSettings: { throttlingRateLimit: 20, throttlingBurstLimit: 40 } },
      },
    });
    api.routePrivate("$default", service.arn);

    return { url: api.url, server: server.id, table: table.name, repo: repo.repositoryUrl };
  },
});
