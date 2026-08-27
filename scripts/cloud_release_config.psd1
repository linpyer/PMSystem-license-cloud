@{
    ProjectName = 'DDREC License Cloud'
    ProductionBranch = 'v1.3'
    VersionFile = 'VERSION'
    Environments = @{
        production = @{
            ApiBaseUrl = 'https://license.aixcc.top/api/v1'
            PublicBaseUrl = 'https://license.aixcc.top'
            AdminBaseUrl = 'https://license.aixcc.top/admin/'
            AdminEnvironment = 'production'
            AdminLabel = '生产环境'
            AdminTitle = 'iVRec 授权管理'
            AdminBasePath = '/admin/'
        }
    }
}
