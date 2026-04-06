import requests

# 测试登录
login_url = 'http://localhost:5000/api/auth/login'
login_data = {'username': 'testuser', 'password': 'password123'}

response = requests.post(login_url, json=login_data)
print('登录响应:', response.status_code, response.json())

# 获取会话cookie
cookies = response.cookies
print('会话cookie:', cookies)

# 测试创建任务
tasks_url = 'http://localhost:5000/api/tasks'
task_data = {
    'title': '测试任务',
    'description': '这是一个测试任务',
    'is_important': True,
    'is_urgent': False,
    'due_at': '2026-04-10T23:59:59Z'
}

response = requests.post(tasks_url, json=task_data, cookies=cookies)
print('创建任务响应:', response.status_code, response.json())

# 测试获取任务列表
response = requests.get(tasks_url, cookies=cookies)
print('获取任务列表响应:', response.status_code, response.json())
