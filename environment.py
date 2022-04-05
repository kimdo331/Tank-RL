import numpy as np
import random
import sys
import time
from requests import get

import TankAPI

IP = '125.137.27.125'
PLAYERNAME = 'dohyun'
TURN = 100
DILATION = 100

# 강화학습 하기에 편리하도록 인터페이스를 제공하는 클래스
class Environment():
    '''
    ### state
    
    0) 32x32 전체 지도, 0은 모르는 공간, 1~4는 아군 탱크, 5는 적 탱크, 6은 장애물, 7은 빈 공간
    1) 1번 전차 정보, [HP, AP, angle]
    2) 2번 전차 정보, [HP, AP, angle]
    3) 3번 전차 정보, [HP, AP, angle]
    4) 4번 전차 정보, [HP, AP, angle]
    5) 적 탱크의 수
    정보에서 각도는 45의 배수이면서 [0, 360) 사이의 값이어야 함
    
    # memo: 필요 시 아군탱크, 적탱크, 장애물 리스트를 각각 지정할 수도.
    
    
    ### action
    
    type: single integer
    
    0: attack
    1: rotate +45
    2: rotate -45
    3: move south ↓
    4: move north ↑
    5: move east →
    6: move west ←
    7: turn end
    
    
    ### reward
    
    - 적 전차 맞추면 +50
    - 적 전차 잡으면 +100
    - 아군 전차 맞으면 -50
    - 아군 전차 잡히면 -100
    
    '''
    
    def __init__(self):
        # state
        self.map = np.zeros((32, 32), dtype=np.int32)
        self.tank_info = np.zeros((4, 3), dtype=np.int32)
        self.turn_tank = 1 # 우리 탱크(1 ~ 4) 중 누구의 턴인지
        self.enemy_num = 4
        
        self.tankAPI = TankAPI.TankAPI()
    
    # 세션 맨 처음에 생성
    def start(self, ip=IP, playername=PLAYERNAME, turn=TURN, dilation=DILATION):
        self.tankAPI.ip, self.tankAPI.playername, self.tankAPI.turn, self.tankAPI.dilation = ip, playername, turn, dilation
        
        print('ip:',ip)
        self.tankAPI.session_resource()
        self.tankAPI.session_create()
    
    # 세션 초기화 및 정보 가져오기
    def reset(self):
        
        self.tankAPI.session_reset()
        self.tankAPI.session_join()
        
        status = self.tankAPI.game_status()
        agents = status['responses']['data']['message']['agent_info']['agent']
        
        for agentIdx in range(len(agents)):
            agent = agents[agentIdx]
            self.tank_info[agentIdx] = [agent['hp'], agent['ap'], 0]
        
        self._set_map()
        state = self._get_state()
        
        return state
    
    
    def _set_map(self, enemy_tank_update = False):
        # 내 턴에서 이동할 때에는 상대 탱크 업데이트 하지 않음
        # 내 턴에서 공격할 때에는 상대 탱크 업데이트 수행함
        status = self.tankAPI.game_status()
        agents = status['responses']['data']['message']['agent_info']['agent']
        
        # 아군탱크였던 부분을 빈공간으로 만듦
        # 장애물 위치, 빈공간 위치는 유지.
        for i in range(32):
            for j in range(32):
                if self.map[i][j] == 1 or \
                    self.map[i][j] == 2 or \
                    self.map[i][j] == 3 or \
                    self.map[i][j] == 4:
                    self.map[i][j] = 7
                if enemy_tank_update and self.map[i][j] == 5:
                    self.map[i][j] = 0 # 상대 탱크 있었던 위치를 '모름'으로 바꿈
        
        _, gameMap = self.tankAPI.game_view()
        for i in range(32):
            for j in range(32):
                if enemy_tank_update and gameMap.game_map[i][j] == 1: # 상대 탱크
                    self.map[i][j] = 5
                elif gameMap.game_map[i][j] == 3: # 장애물
                    self.map[i][j] = 6
        
        for agentIdx in range(len(agents)):
            agent = agents[agentIdx]
            
            i, j = self._location2idx(agent['location'])
            self.map[i][j] = agentIdx+1 # 아군 탱크

            # 아군 탱크에서 5만큼 떨어진 공간까지는 빈공간인걸 안다.
            dij = [(i,j) for i in range(-5, 6) for j in range(-5, 6)] # (-5, -5) ~ (5, 5)
            for d in dij:
                ii = d[0] + i
                jj = d[1] + j
                if ii < 0 or ii > 31 or jj < 0 or jj > 31:
                    continue
                if self.map[ii][jj] == 0:
                    self.map[ii][jj] = 7
            
            # 바라보는 방향으로 빈 공간을 안다.
            dir = self._angle2direction(self.tank_info[agentIdx][2])
            ii, jj = i, j # 반복문 내에서만 쓰는 변수
            while True:
                ii += dir[0]
                jj += dir[1]
                if ii < 0 or ii > 31 or jj < 0 or jj > 31:
                    break
                if self.map[ii][jj] == 0:
                    self.map[ii][jj] = 7
    
    
    def _location2idx(self, location):
        x, y = location[0], location[1]
        j = (x-25200)//1000
        i = (y-147450)//1000
        
        assert 0 <= j <= 31 and 0 <= i <= 31
        return i, j # usage: map[i][j]
    
    # e.g., angle이 45도일때 (1,-1)을 리턴
    def _angle2direction(self, angle):
        assert angle%45 == 0
        angle_directions = [(1,0), (1,-1), (0,-1), (-1,-1), (-1,0), (-1,1), (0,1), (1,1)]
        angleIdx = angle // 45
        return angle_directions[angleIdx]
        
    
    def _get_our_tank_num(self):
        num = 0
        if self.tank_info[0][0] != 0:
            num += 1
        if self.tank_info[1][0] != 0:
            num += 1
        if self.tank_info[2][0] != 0:
            num += 1
        if self.tank_info[3][0] != 0:
            num += 1
        return num
    
    # 현재 조종할 탱크를 기준으로 수행할 수 있는 액션만 반환
    def legal_actions(self):
        # memo: 가고싶은 곳에 장애물 있어도 갈 수 있는 경우 있어서, 장애물이 갈 길을 막고있는 상황은 고려하지 않았음
        actions = []
        hp, ap, angle = self.tank_info[self.turn_tank-1]
        
        if hp <= 0:
            actions = [7]
            return actions
        if ap >= 4:
            actions = [0, 1, 2, 3, 4, 5, 6, 7]
            return actions
        if ap >= 2:
            actions = [1, 2, 3, 4, 5, 6, 7]
            return actions
        if ap >= 1:
            actions = [1, 2, 7]
            return actions
        if ap == 0:
            actions = [7]
            return actions
    
    # 액션을 받아 한 단계 실행하는 함수
    def step(self, action):
        action = action[0][0]
        assert action in self.legal_actions()
        reward = 0
        hit = False
        enemy_tank_update = False
        
        status = self.tankAPI.game_status()
        agents = status['responses']['data']['message']['agent_info']['agent']
        agent = agents[self.turn_tank-1]
        uid = agent['uid']
        if action == 0: # attack
            print(uid, '-> attack')
            # 포신 방향에서 가장 첫번째에 적이 있었으면 (==포탄이 장애물에 막히지 않으면)
            dir = self._angle2direction(self.tank_info[self.turn_tank-1][2])
            ii, jj = agent['location'][0], agent['location'][1]
            while True:
                ii += dir[0]
                jj += dir[1]
                if ii < 0 or ii > 31 or jj < 0 or jj > 31: # map 밖으로 나가면 중단
                    break
                elif self.map[ii][jj] == 7: # 빈공간이면 계속 나아감
                    continue
                elif self.map[ii][jj] == 6: # 장애물이면 그만둠
                    break
                elif self.map[ii][jj] == 5: # 적이면 타격성공
                    reward += 50
                    hit = True
                    enemy_tank_update = True
                    print('hit!')
                else: # TODO: 아군에게 쏜다면??????????????
                    break
                
                self.tankAPI.agent_attack(uid)
        
        elif action == 1: # rotate +45 (오른쪽 ↻)
            print(uid, '-> rotate +45')
            self.tankAPI.agent_rotate(uid, 45)
            self.tank_info[self.turn_tank-1][2] = (self.tank_info[self.turn_tank-1][2] + 45) % 360
        
        elif action == 2: # rotate -45 (왼쪽 ↺)
            print(uid, '-> rotate -45')
            self.tankAPI.agent_rotate(uid, -45)
            self.tank_info[self.turn_tank-1][2] = (self.tank_info[self.turn_tank-1][2] - 45) % 360
            
        elif action == 3: # move south ↓
            print(uid, '-> move south')
            self.tankAPI.agent_move(uid, 0)
            
        elif action == 4: # move north ↑
            print(uid, '-> move north')
            self.tankAPI.agent_move(uid, 2) # TODO: move 4개의 코드 맞는지 테스트
        
        elif action == 5: # move east →
            print(uid, '-> move east')
            self.tankAPI.agent_move(uid, 1)
        
        elif action == 6: # move west ←
            print(uid, '-> move west')
            self.tankAPI.agent_move(uid, 3)
        
        elif action == 7: # turn end
            print(uid, '-> turn end\n')
            if self.turn_tank == 4:
                self.turn_tank = 1
                enemy_tank_update = True
                print('wait enemy')
                self._wait_enemy()
            else:
                self.turn_tank += 1
        
        
        ## self.map과 self.tank_info 업데이트
        
        status = self.tankAPI.game_status()
        agents = status['responses']['data']['message']['agent_info']['agent']
        
        for agentIdx in range(len(agents)):
            agent = agents[agentIdx]
            if self.tank_info[agentIdx][0] != agent['hp']: # 피격당했다면
                reward -= self.tank_info[agentIdx][0] - agent['hp']
            self.tank_info[agentIdx] = [agent['hp'], agent['ap'], self.tank_info[agentIdx][2]]
        
        # 적을 타격했거나 내 턴이 완전히 끝난 경우는 업데이트
        self._set_map(enemy_tank_update=enemy_tank_update)
        
        
        ## reward 판단하기
        
        # 내가 쏜 포에 상대가 맞았는데 상대가 사라졌으면
        if hit:
            if self.map[ii][jj] == 7:
                reward += 100
        
        # 적 턴 종료 한 후
        if action == 7 and self.turn_tank == 1:
            print(f'our: {self._get_our_tank_num()}, enemy:{self.enemy_num}')
            print('turn', status['responses']['data']['message']['game_info']['TurnCount'], '\n')
        
        ## 종료 여부 판단하기
        info = None
        done = False
        if self.enemy_num == 0:
            done = True
            info = 'win'
        elif np.count_nonzero(self.map == 1) +\
                np.count_nonzero(self.map == 2) +\
                np.count_nonzero(self.map == 3) +\
                np.count_nonzero(self.map == 4) == 0:
            done = True
            info = 'lose'
        
        state = self._get_state()
        
        return state, reward, done, info
    
    # 1041개 짜리 1차원 리스트로 리턴
    def _get_state(self):
        # return {'map': self.map, 'tank_info': self.tank_info, 'turn_tank': self.turn_tank, 'enemy_num': self.enemy_num}
        # return self.map, self.tank_info, self.turn_tank, self.enemy_num
        ret = []
        for x in self.map:
            for y in x:
                ret.append(y)
        for x in self.tank_info:
            for y in x:
                ret.append(y)
        ret.append(self.turn_tank)
        ret.append(self.enemy_num)
        return ret
        
    
    # 내 턴이 끝나고 상대 턴을 기다리는 함수
    def _wait_enemy(self):
        self.tankAPI.game_endturn()
        while True:
            isTurnOwner = self.tankAPI.game_status()['responses']['data']['message']['game_info']['IsTurnOwner']
            if not isTurnOwner:
                time.sleep(5)
            else:
                break
    
    
    # 지금까지 진행된 상황 뿌려주기
    def render(self):
        print('-'*62)
        for i in range(32):
            for j in range(32):
                if self.map[i][j] == 0:
                    print(' ', end=' ') # 모르는공간
                elif self.map[i][j] == 5:
                    print('T', end=' ') # 상대탱크
                elif self.map[i][j] == 6:
                    print('O', end=' ') # 장애물
                elif self.map[i][j] == 7:
                    print('·', end=' ') # 빈공간
                else:
                    print(self.map[i][j], end=' ')
            print()
        print('-'*62)
        print()
    

if __name__ == '__main__':
    ip = get('https://api.ipify.org').text
    print('ip:', ip)
    env = Environment()
    env.reset(ip=ip)
    env.render()
    
    while True:
        actions = env.legal_actions()
        state, reward, done, info = env.step(random.choice(actions))
        if reward != 0:
            print('reward:', reward)
        env.render()
        if done:
            print('*'*30,'\n\ndone!', info)
            break



'''
# 이 식 잘못되었을 확률 매우높음
x = (x-25200)//1000
y = (y-147450)//1000

exepted -1 19

x원래 = 24200
y원래 = 166450

[24200, 166450]

---

east와 west 반대로 된 듯
move 명령 내렸는데 위치가 이전과 동일하다? 음의 reward

---

('Connection aborted.', ConnectionResetError(10054, '', None, 10054, None))
(Caused by NewConnectionError('<urllib3.connection.HTTPConnection object at 0x000001B2617407F0>: Failed to establish a new connection: [WinError 10061] 대상 컴퓨터에서 연결을 거부했으므로 연결하지 못했습니다'))

'''