// SPDX-License-Identifier: MIT
pragma solidity ^0.8.17;

/*
  Простой StakingContract для ERC20-токена.
  - Пользователь делает approve(...) на этот контракт,
  - Затем вызывает stake(amount).
  - При unstake берётся 1% fee, возвращаем остальное.
  - 12% годовых начисляется пропорционально времени.
*/

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract StakingContract is Ownable {
    IERC20 public stakingToken;  // Токен, который стейкаем

    // APY = 12% = 0.12 в год
    // В секундах в году ~ 31536000
    // rewardPerSecond = 0.12 / 31536000 = ~3.80e-9
    // Но для избежания float будем считать всё в целых, см. формулу.

    uint256 public annualPercentBP = 1200; // 12.00% в виде базисных пунктов (BP). 1200 = 12%
    uint256 public constant SECONDS_PER_YEAR = 365 days; 
    // Структура пользователя
    struct UserInfo {
        uint256 staked;       // Сколько застейкано
        uint256 rewardDebt;   // Сколько наград уже насчитано
        uint256 lastUpdate;   // Последний раз, когда обновляли
    }

    mapping(address => UserInfo) public users;

    // Куда идут сервисные сборы (5$)
    address public feeReceiver;

    // События
    event Staked(address indexed user, uint256 amount);
    event Unstaked(address indexed user, uint256 amountOut, uint256 fee);
    event Claimed(address indexed user, uint256 reward);

    constructor(IERC20 _stakingToken, address _feeReceiver) {
        stakingToken = _stakingToken;
        feeReceiver = _feeReceiver;
    }

    // Вспомогательная функция подсчёта накопленных наград
    function _pendingRewards(address _user) internal view returns (uint256) {
        UserInfo memory u = users[_user];
        if (u.staked == 0) {
            return 0;
        }
        uint256 timeDiff = block.timestamp - u.lastUpdate;
        // Годовой % = 12%. За timeDiff секунд ~ timeDiff / SECONDS_PER_YEAR доля года
        // reward = staked * annualPercentBP/10000 * (timeDiff / SECONDS_PER_YEAR)
        // Чтобы не иметь float, множим:
        // reward = staked * annualPercentBP * timeDiff / SECONDS_PER_YEAR / 10000
        uint256 reward = (u.staked * annualPercentBP * timeDiff) / SECONDS_PER_YEAR / 10000;
        return reward;
    }

    // Обновить награду user
    function _updateRewards(address _user) internal {
        uint256 pending = _pendingRewards(_user);
        if (pending > 0) {
            users[_user].rewardDebt += pending;
        }
        users[_user].lastUpdate = block.timestamp;
    }

    function setFeeReceiver(address _newReceiver) external onlyOwner {
        feeReceiver = _newReceiver;
    }

    // stake(amount)
    // Пользователь должен сделать approve на этот контракт
    function stake(uint256 amount) external {
        require(amount >= 25 * 10**18, "Need at least 25 tokens to stake (5$ + 20$).");

        // Сначала переводим amount с пользователя на контракт
        bool ok = stakingToken.transferFrom(msg.sender, address(this), amount);
        require(ok, "transferFrom failed");

        // 5$ (в токенах) сразу отправим на feeReceiver (для простоты 5*1e18)
        // Остальное - в стейк
        uint256 feePart = 5 * 10**18;
        // На самом деле, можно вычислять курс, но тут условно
        require(amount >= feePart, "Not enough to cover 5$ fee.");
        // Отправляем fee
        bool feeOk = stakingToken.transfer(feeReceiver, feePart);
        require(feeOk, "transfer feePart failed");

        uint256 stakePart = amount - feePart;  // ~20 * 1e18

        // Обновляем награду
        _updateRewards(msg.sender);

        // Увеличиваем staked
        users[msg.sender].staked += stakePart;

        emit Staked(msg.sender, stakePart);
    }

    // Получить награду (без unstake)
    function claimRewards() public {
        _updateRewards(msg.sender);
        uint256 reward = users[msg.sender].rewardDebt;
        require(reward > 0, "No rewards");
        users[msg.sender].rewardDebt = 0;
        // Отправляем награду
        bool ok = stakingToken.transfer(msg.sender, reward);
        require(ok, "transfer reward failed");
        emit Claimed(msg.sender, reward);
    }

    // unstake: вывод всей суммы + награды, удерживаем 1% комиссии
    function unstake() external {
        UserInfo storage u = users[msg.sender];
        require(u.staked > 0, "Nothing staked");

        // Сначала claimRewards (вручную, чтобы всё в одной транзакции)
        _updateRewards(msg.sender);
        uint256 reward = u.rewardDebt;
        if (reward > 0) {
            u.rewardDebt = 0;
            bool okReward = stakingToken.transfer(msg.sender, reward);
            require(okReward, "transfer reward failed");
            emit Claimed(msg.sender, reward);
        }

        // unstake
        uint256 amount = u.staked;
        u.staked = 0;
        uint256 fee = (amount * 100) / 10000; // 1% (100 BP)
        uint256 toUser = amount - fee;

        // fee -> feeReceiver
        bool feeOk = stakingToken.transfer(feeReceiver, fee);
        require(feeOk, "Fee transfer fail");
        // toUser -> user
        bool ok = stakingToken.transfer(msg.sender, toUser);
        require(ok, "unstake transfer fail");

        emit Unstaked(msg.sender, toUser, fee);
    }

    // Узнать, сколько у пользователя застейкано
    function stakeOf(address user) external view returns (uint256) {
        return users[user].staked;
    }

    // Узнать, сколько у него ещё не забранных наград
    function pendingRewards(address user) external view returns (uint256) {
        return _pendingRewards(user) + users[user].rewardDebt;
    }
}
