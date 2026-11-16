"""Integration and gameplay simulation checks."""
from tetris.engine import Piece,Player,empty_board,lock_piece,valid
from tetris.ai import choose
from tetris.puzzles import generate
from tetris.storage import finish_match,load_stats


def test_ai_plays_forty_pieces_without_crash():
    p=Player('AI',seed=8,is_ai=True)
    total=0
    for _ in range(40):
        if p.over:break
        next_kind=p.next[0]
        choice,_=choose(p.board,p.active.kind,next_kind,'normal')
        if not choice:break
        p.active=choice.piece
        p.lock()
        total+=1
    assert total>=15


def test_puzzle_witness_reaches_correct_tspin():
    for d in ('easy','normal','hard'):
        puzzle=generate(37,d)
        b=[row[:] for row in puzzle.board]
        for i,(x,y,r) in enumerate(puzzle.solution):
            p=Piece(puzzle.sequence[i],x,y,r,rotated_last=(i==len(puzzle.solution)-1))
            assert valid(b,p)
            b,n,spin,topped=lock_piece(b,p)
            assert not topped
        assert n>=1 and spin


def test_two_player_same_seed_same_piece_sequence():
    p1=Player('P1',13);p2=Player('P2',13)
    assert p1.active.kind==p2.active.kind
    assert list(p1.next)==list(p2.next)


def test_attack_cancel_incoming():
    p=Player('P1',12)
    p.pending=2
    for y in range(16,20):
        p.board[y]=['G']*10
        p.board[y][4]=None
    p.active=Piece('I',2,16,1)
    res=p.lock()
    assert res.lines==4 and res.attack==2 and p.pending==0

def test_puzzle_keyboard_path_is_real_and_wins():
    from tetris.puzzles import solve_spin_actions
    from tetris.engine import ghost
    challenge=generate(26,'easy')
    route=solve_spin_actions(challenge.board)
    assert route and 'cw' in route or route and 'ccw' in route
    p=Player('P1',seed=26)
    p.board=[r[:] for r in challenge.board]
    p.active=Piece('T')
    for step in route:
        if step=='left':assert p.move(-1,0)
        if step=='right':assert p.move(1,0)
        if step=='down':assert p.move(0,1)
        if step=='cw':assert p.rotate(1)
        if step=='ccw':assert p.rotate(-1)
    p.active=ghost(p.board,p.active)
    b,n,spin,topped=lock_piece(p.board,p.active)
    assert spin and n>0 and not topped
