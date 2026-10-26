import { describe,expect,it,vi } from 'vitest'
import { apiClient } from './client'
import { getHealth } from './system'
describe('system API',()=>{it('unwraps backend response',async()=>{vi.spyOn(apiClient,'get').mockResolvedValueOnce({data:{success:true,message:'请求成功',data:{status:'healthy',database:'connected',timestamp:'2026-01-01T00:00:00Z'}}});await expect(getHealth()).resolves.toMatchObject({status:'healthy',database:'connected'})})})
