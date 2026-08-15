@{
    ProjectName = 'DDREC License Cloud'
    ProductionBranch = 'v1.3'
    VersionFile = 'VERSION'
    Environments = @{
        local = @{
            ApiBaseUrl = 'http://127.0.0.1:8000/api/v1'
            PublicBaseUrl = 'http://127.0.0.1:8000'
            AdminBaseUrl = 'http://127.0.0.1:5173'
            AdminEnvironment = 'local'
            AdminLabel = '本地环境'
            AdminTitle = 'DD Rec 授权管理（本地）'
            AdminBasePath = '/admin/'
        }
        production = @{
            ApiBaseUrl = 'https://license.aixcc.top/api/v1'
            PublicBaseUrl = 'https://license.aixcc.top'
            AdminBaseUrl = 'https://license.aixcc.top/admin/'
            AdminEnvironment = 'production'
            AdminLabel = '生产环境'
            AdminTitle = 'DD Rec 授权管理'
            AdminBasePath = '/admin/'
        }
    }
}
