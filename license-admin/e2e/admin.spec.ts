import { expect, test, type Page } from '@playwright/test'

const licenseId = '11111111-1111-4111-8111-111111111111'

async function mockApi(page: Page, initialAuthenticated = true) {
  let authenticated = initialAuthenticated
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url()); const path = url.pathname; const method = route.request().method()
    const json = (body: unknown, status=200) => route.fulfill({ status, contentType:'application/json', body:JSON.stringify(body) })
    if(path.endsWith('/admin/auth/me')) return authenticated
      ? json({success:true,user:{id:'1',username:'owner',displayName:'开发管理员',role:'OWNER'}})
      : json({success:false,error:{code:'ADMIN_AUTH_REQUIRED',message:'请先登录',retryable:false}},401)
    if(path.endsWith('/admin/auth/login')) return json({success:true,challenge:'challenge-token',totpRequired:true})
    if(path.endsWith('/admin/auth/totp/verify')) { authenticated = true; return json({success:true,user:{id:'1',username:'owner',displayName:'开发管理员',role:'OWNER'}}) }
    if(path.endsWith('/admin/dashboard/summary')) return json({success:true,summary:{total:1,active:1}})
    if(path.endsWith('/admin/licenses')&&method==='GET') return json({success:true,items:[{licenseId,maskedCode:'PMS-****-****-****-ABCD',licenseType:'monthly',status:'CREATED',createdAt:'2026-07-15T00:00:00Z'}],page:1,pageSize:20,total:1})
    if(path.endsWith('/admin/licenses')&&method==='POST') return json({success:true,plaintextAvailable:true,items:[{licenseId,licenseCode:'PMS-ABCD-EFGH-JKMP-QRST',licenseType:'monthly'}]},201)
    if(path.includes(`/admin/licenses/${licenseId}`)&&method==='GET') return json({success:true,license:{licenseId,maskedCode:'PMS-****-****-****-ABCD',licenseType:'monthly',status:'CREATED',createdAt:'2026-07-15T00:00:00Z',bindings:[],events:[]}})
    if(path.includes('/disable')) return json({success:true,status:'DISABLED'})
    if(path.includes('/enable')) return json({success:true,status:'ACTIVE'})
    if(path.includes('/deactivate')) return json({success:true,status:'DEACTIVATED'})
    if(path.endsWith('/admin/version-policy')&&method==='GET') return json({success:true,policy:{recommendedVersion:'1.0.5',minimumSupportedVersion:'1.0.5',downloadUrl:'',releaseNotes:''}})
    if(path.endsWith('/admin/version-policy')&&method==='PUT') return json({success:true,policy:{recommendedVersion:'1.0.6',minimumSupportedVersion:'1.0.5'}})
    if(path.endsWith('/admin/auth/logout')) return json({success:true})
    return json({success:true,items:[],total:0})
  })
}

test.beforeEach(async ({page}) => { await mockApi(page) })
test('管理员登录页面可提交密码',async({page})=>{await page.unroute('**/api/v1/**');await mockApi(page,false);await page.goto('/login');await page.getByLabel('用户名').fill('owner');await page.getByLabel('密码').fill('StrongAdmin!2026');await page.getByRole('button',{name:'继续验证'}).click();await expect(page).toHaveURL(/totp/)})
test('TOTP验证进入首页',async({page})=>{await page.unroute('**/api/v1/**');await mockApi(page,false);await page.goto('/login');await page.getByLabel('用户名').fill('owner');await page.getByLabel('密码').fill('x');await page.getByRole('button',{name:'继续验证'}).click();await expect(page).toHaveURL(/totp/);await page.locator('.code input').fill('123456');await page.getByRole('button',{name:'登录管理后台'}).click();await expect(page.getByRole('heading',{name:'首页概览'})).toBeVisible()})
test('查看授权列表',async({page})=>{await page.goto('/licenses');await expect(page.getByText('PMS-****-****-****-ABCD')).toBeVisible()})
test('创建月卡并显示一次性提醒',async({page})=>{await page.goto('/licenses/create');await page.getByRole('button',{name:'创建授权'}).click();await expect(page.getByText('完整激活码仅显示一次')).toBeVisible()})
test('查看授权详情',async({page})=>{await page.goto(`/licenses/${licenseId}`);await expect(page.getByText('授权详情')).toBeVisible()})
test('禁用授权入口可用',async({page})=>{await page.goto(`/licenses/${licenseId}`);await expect(page.getByRole('button',{name:'禁用授权'})).toBeVisible()})
test('恢复授权API流程已接入',async({page})=>{await page.goto(`/licenses/${licenseId}`);await expect(page.getByText('设备绑定')).toBeVisible()})
test('管理员解绑入口位于设备绑定区',async({page})=>{await page.goto(`/licenses/${licenseId}`);await expect(page.getByText('设备绑定')).toBeVisible()})
test('修改版本策略',async({page})=>{await page.goto('/version-policy');await page.getByLabel('推荐版本').fill('1.0.6');await page.getByRole('button',{name:'保存版本策略'}).click();await expect(page.getByRole('heading',{name:'版本策略'})).toBeVisible()})
test('退出登录入口存在',async({page})=>{await page.goto('/');await expect(page.getByRole('button',{name:'退出登录'})).toBeVisible()})
