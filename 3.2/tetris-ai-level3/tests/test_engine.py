import pytest
from tetris.engine import (W,H,Piece,Bag,Player,empty_board,valid,ghost,try_rotate,lock_piece,stats,clear_lines,corners_blocked,is_t_spin)
from tetris.ai import choose,landings,preview_at
from tetris.puzzles import generate,validate_puzzle,legal_spin_locks
from tetris.storage import load_stats,save_stats,finish_match

def test_seven_pieces_are_bags():
    b=Bag(19);assert len({b.take() for _ in range(7)})==7

def test_bag_seed_reproducible():
    a,b=Bag(2),Bag(2)
    assert [a.take() for _ in range(25)]==[b.take() for _ in range(25)]

def test_all_pieces_have_four_cells():
    for kind in 'IJLOSTZ':
        for r in range(4):
            from tetris.engine import cells
            assert len(cells(kind,r))==4
            assert len(set(cells(kind,r)))==4

def test_wall_and_floor_collision():
    board=empty_board()
    assert not valid(board,Piece('I',-3,0))
    assert not valid(board,Piece('O',4,19))

def test_ghost_is_landing():
    b=empty_board();p=Piece('T');g=ghost(b,p)
    assert valid(b,g)
    below=g.copy();below.y+=1
    assert not valid(b,below)

def test_line_clear_exact():
    b=empty_board();b[-1]=['G']*10
    b2,n=clear_lines(b)
    assert n==1 and b2[0]==[None]*10 and b2[-1]==[None]*10

def test_srs_rotation_kicks_near_wall():
    b=empty_board();p=Piece('T',-1,1,1)
    assert valid(b,p)
    q=try_rotate(b,p,-1)
    assert q is not None and valid(b,q) and q.rot==0

def test_t_spin_requires_rotation_and_corner_occupancy():
    p=generate(42,'easy')
    b=p.board
    found=legal_spin_locks(b)
    assert found
    t,n=found[0];assert is_t_spin(b,t) and n>=1
    t.rotated_last=False
    assert not is_t_spin(b,t)

def test_attack_tetris_four_lines():
    p=Player('P1',1)
    for y in range(H-4,H):
        p.board[y]=['G']*W
        p.board[y][4]=None
    # I vertical rotation 1 fills four empty column slots.
    from tetris.engine import cells
    q=Piece('I',2,H-4,1)
    filled=[(x,y) for x,y in q.squares()]
    assert {x for x,y in filled}=={4}
    assert valid(p.board,q)
    p.active=q
    r=p.lock()
    assert r.lines==4 and r.attack>=4 and p.lines==4

def test_hold_is_once_per_piece():
    p=Player('P1',2);original=p.active.kind
    assert p.hold() and p.held==original
    assert not p.hold()
    p.hard_drop()
    assert p.hold()

def test_garbage_and_cancel():
    p=Player('P1',2)
    p.receive_garbage(2)
    assert sum(x is None for x in p.board[-1])==1
    assert sum(x is None for x in p.board[-2])==1

def test_ai_valid_placements():
    p=Player('P1',5)
    for d in ['easy','normal','hard']:
        best,candidates=choose(p.board,p.active.kind,p.next[0],d)
        assert best is not None and len(candidates)>=10
        assert candidates[0].score>=candidates[-1].score
        assert valid(p.board,best.piece)

def test_ai_evaluation_parts():
    p=Player('P1',5)
    a=preview_at(p.board,p.active)
    assert a and '구멍 변화' in a.parts and '평탄화' in a.parts

def test_puzzle_generation_and_validation():
    for level,count in [('easy',1),('normal',2),('hard',3)]:
        for seed in [1,2,3]:
            puzzle=generate(seed,level)
            assert len(puzzle.sequence)==count
            assert validate_puzzle(puzzle)
            assert len(puzzle.solution)==count

def test_puzzle_solution_reproducible():
    a,b=generate(99,'hard'),generate(99,'hard')
    assert a.board==b.board and a.solution==b.solution

def test_save_load_json(tmp_path):
    path=tmp_path/'save.json';stats=load_stats(path)
    assert stats['matches']==0
    p=Player('P1',7);p.score=1000
    finish_match(stats,[p]);save_stats(path,stats)
    loaded=load_stats(path)
    assert loaded['matches']==1 and loaded['best_score']['P1']==1000

def test_corrupted_records_fallback(tmp_path):
    path=tmp_path/'corrupt.json';path.write_text('{bad json')
    assert load_stats(path)['matches']==0

def test_garbage_topout():
    p=Player('P1',7)
    p.board[0][0]='G'
    p.receive_garbage(1)
    assert p.over
