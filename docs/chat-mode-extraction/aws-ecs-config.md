# AWS ECS Deployment Configuration

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AWS Cloud                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        VPC (10.0.0.0/16)                            │   │
│  │                                                                      │   │
│  │  ┌──────────────────────┐    ┌──────────────────────┐              │   │
│  │  │   Public Subnet A    │    │   Public Subnet B    │              │   │
│  │  │   (10.0.1.0/24)      │    │   (10.0.2.0/24)      │              │   │
│  │  │                      │    │                      │              │   │
│  │  │  ┌────────────────┐  │    │  ┌────────────────┐  │              │   │
│  │  │  │      ALB       │◄─┼────┼──│    Route 53    │  │              │   │
│  │  │  │  (WebSocket    │  │    │  │                │  │              │   │
│  │  │  │   Enabled)     │  │    │  └────────────────┘  │              │   │
│  │  │  └───────┬────────┘  │    │                      │              │   │
│  │  └──────────┼───────────┘    └──────────────────────┘              │   │
│  │             │                                                       │   │
│  │  ┌──────────┼───────────┐    ┌──────────────────────┐              │   │
│  │  │  Private│Subnet A   │    │   Private Subnet B    │              │   │
│  │  │  (10.0.3.0/24)      │    │   (10.0.4.0/24)      │              │   │
│  │  │         │           │    │                      │              │   │
│  │  │  ┌──────▼────────┐  │    │  ┌────────────────┐  │              │   │
│  │  │  │  ECS Fargate  │  │    │  │  ECS Fargate   │  │              │   │
│  │  │  │  Task (Chat)  │  │    │  │  Task (Chat)   │  │              │   │
│  │  │  │               │  │    │  │                │  │              │   │
│  │  │  └───────────────┘  │    │  └────────────────┘  │              │   │
│  │  └─────────────────────┘    └──────────────────────┘              │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐            │
│  │      ECR        │  │   CloudWatch    │  │  Secrets Mgr    │            │
│  │  (Container     │  │   (Logs &       │  │  (API Keys)     │            │
│  │   Registry)     │  │    Metrics)     │  │                 │            │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 1. ECS Task Definition

```json
{
  "family": "chat-service",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::ACCOUNT_ID:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::ACCOUNT_ID:role/chatServiceTaskRole",
  "containerDefinitions": [
    {
      "name": "chat-service",
      "image": "ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/chat-service:latest",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "PORT",
          "value": "8000"
        },
        {
          "name": "LOG_LEVEL",
          "value": "INFO"
        }
      ],
      "secrets": [
        {
          "name": "BACKEND_URL",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT_ID:secret:chat-service/backend-url"
        },
        {
          "name": "BRAVE_API_KEY",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT_ID:secret:chat-service/brave-api-key"
        },
        {
          "name": "TOGETHER_API_KEY",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT_ID:secret:chat-service/together-api-key"
        },
        {
          "name": "OPENAI_API_KEY",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT_ID:secret:chat-service/openai-api-key"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/chat-service",
          "awslogs-region": "REGION",
          "awslogs-stream-prefix": "chat"
        }
      },
      "healthCheck": {
        "command": ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 60
      }
    }
  ]
}
```

## 2. ECS Service Definition

```json
{
  "serviceName": "chat-service",
  "cluster": "production-cluster",
  "taskDefinition": "chat-service:LATEST",
  "desiredCount": 2,
  "launchType": "FARGATE",
  "platformVersion": "LATEST",
  "networkConfiguration": {
    "awsvpcConfiguration": {
      "subnets": [
        "subnet-private-a",
        "subnet-private-b"
      ],
      "securityGroups": ["sg-chat-service"],
      "assignPublicIp": "DISABLED"
    }
  },
  "loadBalancers": [
    {
      "targetGroupArn": "arn:aws:elasticloadbalancing:REGION:ACCOUNT_ID:targetgroup/chat-service-tg/xxx",
      "containerName": "chat-service",
      "containerPort": 8000
    }
  ],
  "healthCheckGracePeriodSeconds": 120,
  "deploymentConfiguration": {
    "maximumPercent": 200,
    "minimumHealthyPercent": 100,
    "deploymentCircuitBreaker": {
      "enable": true,
      "rollback": true
    }
  },
  "enableExecuteCommand": true
}
```

## 3. Application Load Balancer (WebSocket-Enabled)

### Target Group Configuration

```json
{
  "Name": "chat-service-tg",
  "Protocol": "HTTP",
  "Port": 8000,
  "VpcId": "vpc-xxx",
  "HealthCheckProtocol": "HTTP",
  "HealthCheckPath": "/health",
  "HealthCheckIntervalSeconds": 30,
  "HealthyThresholdCount": 2,
  "UnhealthyThresholdCount": 3,
  "TargetType": "ip",
  "Matcher": {
    "HttpCode": "200"
  },
  "Attributes": [
    {
      "Key": "stickiness.enabled",
      "Value": "true"
    },
    {
      "Key": "stickiness.type",
      "Value": "lb_cookie"
    },
    {
      "Key": "stickiness.lb_cookie.duration_seconds",
      "Value": "86400"
    },
    {
      "Key": "deregistration_delay.timeout_seconds",
      "Value": "30"
    }
  ]
}
```

### ALB Listener Rules (WebSocket Support)

```json
{
  "ListenerArn": "arn:aws:elasticloadbalancing:REGION:ACCOUNT_ID:listener/app/chat-alb/xxx/xxx",
  "Rules": [
    {
      "Priority": 10,
      "Conditions": [
        {
          "Field": "path-pattern",
          "Values": ["/ws/*"]
        }
      ],
      "Actions": [
        {
          "Type": "forward",
          "TargetGroupArn": "arn:aws:elasticloadbalancing:REGION:ACCOUNT_ID:targetgroup/chat-service-tg/xxx"
        }
      ]
    },
    {
      "Priority": 20,
      "Conditions": [
        {
          "Field": "path-pattern",
          "Values": ["/*"]
        }
      ],
      "Actions": [
        {
          "Type": "forward",
          "TargetGroupArn": "arn:aws:elasticloadbalancing:REGION:ACCOUNT_ID:targetgroup/chat-service-tg/xxx"
        }
      ]
    }
  ]
}
```

### Important ALB Settings for WebSocket

```hcl
# Terraform example for ALB attributes
resource "aws_lb" "chat_alb" {
  name               = "chat-service-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets            = var.public_subnets

  # Important for WebSocket connections
  idle_timeout = 3600  # 1 hour for long-lived WebSocket connections

  enable_deletion_protection = true

  tags = {
    Name        = "chat-service-alb"
    Environment = "production"
  }
}
```

## 4. Auto Scaling Configuration

```json
{
  "ServiceNamespace": "ecs",
  "ResourceId": "service/production-cluster/chat-service",
  "ScalableDimension": "ecs:service:DesiredCount",
  "MinCapacity": 2,
  "MaxCapacity": 10
}
```

### Scaling Policies

```json
{
  "TargetTrackingScalingPolicies": [
    {
      "PolicyName": "cpu-scaling",
      "TargetTrackingScalingPolicyConfiguration": {
        "TargetValue": 70.0,
        "PredefinedMetricSpecification": {
          "PredefinedMetricType": "ECSServiceAverageCPUUtilization"
        },
        "ScaleInCooldown": 300,
        "ScaleOutCooldown": 60
      }
    },
    {
      "PolicyName": "memory-scaling",
      "TargetTrackingScalingPolicyConfiguration": {
        "TargetValue": 75.0,
        "PredefinedMetricSpecification": {
          "PredefinedMetricType": "ECSServiceAverageMemoryUtilization"
        },
        "ScaleInCooldown": 300,
        "ScaleOutCooldown": 60
      }
    }
  ]
}
```

## 5. Security Group Configuration

```json
{
  "GroupName": "chat-service-sg",
  "Description": "Security group for Chat Service ECS tasks",
  "VpcId": "vpc-xxx",
  "IngressRules": [
    {
      "IpProtocol": "tcp",
      "FromPort": 8000,
      "ToPort": 8000,
      "SourceSecurityGroupId": "sg-alb",
      "Description": "Allow traffic from ALB"
    }
  ],
  "EgressRules": [
    {
      "IpProtocol": "-1",
      "CidrIp": "0.0.0.0/0",
      "Description": "Allow all outbound traffic"
    }
  ]
}
```

## 6. IAM Roles

### Task Execution Role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:REGION:ACCOUNT_ID:log-group:/ecs/chat-service:*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:REGION:ACCOUNT_ID:secret:chat-service/*"
    }
  ]
}
```

### Task Role (for application)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ssmmessages:CreateControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:OpenDataChannel"
      ],
      "Resource": "*"
    }
  ]
}
```

## 7. CloudWatch Alarms

```json
{
  "Alarms": [
    {
      "AlarmName": "chat-service-high-cpu",
      "MetricName": "CPUUtilization",
      "Namespace": "AWS/ECS",
      "Dimensions": [
        {"Name": "ClusterName", "Value": "production-cluster"},
        {"Name": "ServiceName", "Value": "chat-service"}
      ],
      "Statistic": "Average",
      "Period": 300,
      "EvaluationPeriods": 2,
      "Threshold": 85,
      "ComparisonOperator": "GreaterThanThreshold",
      "AlarmActions": ["arn:aws:sns:REGION:ACCOUNT_ID:alerts"]
    },
    {
      "AlarmName": "chat-service-unhealthy-tasks",
      "MetricName": "UnhealthyHostCount",
      "Namespace": "AWS/ApplicationELB",
      "Dimensions": [
        {"Name": "TargetGroup", "Value": "targetgroup/chat-service-tg/xxx"},
        {"Name": "LoadBalancer", "Value": "app/chat-alb/xxx"}
      ],
      "Statistic": "Average",
      "Period": 60,
      "EvaluationPeriods": 2,
      "Threshold": 1,
      "ComparisonOperator": "GreaterThanOrEqualToThreshold",
      "AlarmActions": ["arn:aws:sns:REGION:ACCOUNT_ID:alerts"]
    }
  ]
}
```

## 8. Deployment Pipeline (GitHub Actions)

```yaml
name: Deploy Chat Service to ECS

on:
  push:
    branches: [main]
    paths:
      - 'chat-service/**'
      - '.github/workflows/deploy-chat-service.yml'

env:
  AWS_REGION: us-east-1
  ECR_REPOSITORY: chat-service
  ECS_SERVICE: chat-service
  ECS_CLUSTER: production-cluster
  CONTAINER_NAME: chat-service

jobs:
  deploy:
    name: Deploy
    runs-on: ubuntu-latest
    
    steps:
    - name: Checkout
      uses: actions/checkout@v4

    - name: Configure AWS credentials
      uses: aws-actions/configure-aws-credentials@v4
      with:
        aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
        aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
        aws-region: ${{ env.AWS_REGION }}

    - name: Login to Amazon ECR
      id: login-ecr
      uses: aws-actions/amazon-ecr-login@v2

    - name: Build, tag, and push image to Amazon ECR
      id: build-image
      env:
        ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
        IMAGE_TAG: ${{ github.sha }}
      run: |
        cd chat-service
        docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG -t $ECR_REGISTRY/$ECR_REPOSITORY:latest .
        docker push $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG
        docker push $ECR_REGISTRY/$ECR_REPOSITORY:latest
        echo "image=$ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG" >> $GITHUB_OUTPUT

    - name: Download task definition
      run: |
        aws ecs describe-task-definition --task-definition chat-service \
          --query taskDefinition > task-definition.json

    - name: Fill in the new image ID in the Amazon ECS task definition
      id: task-def
      uses: aws-actions/amazon-ecs-render-task-definition@v1
      with:
        task-definition: task-definition.json
        container-name: ${{ env.CONTAINER_NAME }}
        image: ${{ steps.build-image.outputs.image }}

    - name: Deploy Amazon ECS task definition
      uses: aws-actions/amazon-ecs-deploy-task-definition@v1
      with:
        task-definition: ${{ steps.task-def.outputs.task-definition }}
        service: ${{ env.ECS_SERVICE }}
        cluster: ${{ env.ECS_CLUSTER }}
        wait-for-service-stability: true
```

## 9. Terraform Module (Infrastructure as Code)

```hcl
# main.tf - Chat Service ECS Module

module "chat_service" {
  source = "./modules/ecs-service"

  name        = "chat-service"
  environment = var.environment
  
  # Container configuration
  container_image = "${var.ecr_repository_url}:latest"
  container_port  = 8000
  cpu             = 512
  memory          = 1024
  
  # Networking
  vpc_id          = var.vpc_id
  private_subnets = var.private_subnets
  
  # Load balancer
  alb_arn              = var.alb_arn
  alb_security_group   = var.alb_security_group
  health_check_path    = "/health"
  
  # Auto scaling
  min_capacity = 2
  max_capacity = 10
  
  # Secrets
  secrets = {
    BACKEND_URL     = var.backend_url_secret_arn
    BRAVE_API_KEY   = var.brave_api_key_secret_arn
    TOGETHER_API_KEY = var.together_api_key_secret_arn
    OPENAI_API_KEY  = var.openai_api_key_secret_arn
  }
  
  # Environment variables
  environment_variables = {
    PORT      = "8000"
    LOG_LEVEL = "INFO"
  }

  tags = var.tags
}
```

## 10. Cost Optimization Tips

1. **Right-size containers**: Start with 0.5 vCPU / 1GB memory, monitor and adjust
2. **Use Fargate Spot**: For non-critical workloads, save up to 70%
3. **Enable Container Insights**: Pay for better observability
4. **Use NAT Gateway sharing**: Share across multiple services
5. **Implement request-based scaling**: Scale on WebSocket connections

```json
{
  "capacityProviderStrategy": [
    {
      "capacityProvider": "FARGATE_SPOT",
      "weight": 2,
      "base": 0
    },
    {
      "capacityProvider": "FARGATE",
      "weight": 1,
      "base": 2
    }
  ]
}
```
