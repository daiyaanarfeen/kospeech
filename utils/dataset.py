import math
import random
from torch.utils.data import Dataset
from utils.definition import EOS_token, logger, SOS_token
from utils.feature import spec_augment, get_librosa_melspectrogram, get_torchaudio_melspectrogram
from utils.util import get_label, save_pickle

feature_extract_funtions = {
    'librosa': get_librosa_melspectrogram,
    'torchaudio': get_torchaudio_melspectrogram
}


class SpectrogramDataset(Dataset):
    """
    Dataset for audio & label matchingf

    Args:
        audio_paths (list): set of audio path
        label_paths (list): set of label paths
        sos_id (int): identification of <start of sequence>
        eos_id (int): identification of <end of sequence>
        target_dict (dict): dictionary of filename and labels
        use_augment (bool): flag indication whether to use spec-augmentation or not (default: True)
    """

    def __init__(self, audio_paths, label_paths, sos_id, eos_id, target_dict=None, args=None, use_augment=True):
        self.audio_paths = list(audio_paths)
        self.label_paths = list(label_paths)
        self.sos_id = sos_id
        self.eos_id = eos_id
        self.target_dict = target_dict
        self.augment_num = args.augment_num
        self.augment_flags = [False] * len(self.audio_paths)
        self.get_feature = feature_extract_funtions[args.feature_extract_by]
        self.args = args
        if use_augment:
            self.augmentation()
        self.shuffle()

    def get_item(self, idx):
        label = get_label(self.label_paths[idx], self.sos_id, self.eos_id, self.target_dict)
        spectrogram = self.get_feature(
            self.audio_paths[idx],
            n_mels=self.args.n_mels,
            input_reverse=self.args.input_reverse,
            del_silence=self.args.del_silence,
            normalize=self.args.normalize,
            sr=self.args.sr,
            window_size=self.args.window_size,
            stride=self.args.stride
        )

        if spectrogram is None:  # exception handling
            return None, None

        if self.augment_flags[idx]:
            spectrogram = spec_augment(
                spectrogram,
                time_mask_para=self.args.time_mask_para,
                freq_mask_para=self.args.freq_mask_para,
                time_mask_num=self.args.time_mask_num,
                freq_mask_num=self.args.freq_mask_num
            )

        return spectrogram, label

    def augmentation(self):
        augment_end_idx = int(0 + ((len(self.audio_paths) - 0) * self.augment_num))
        logger.info("Applying Augmentation...")

        for _ in range(self.augment_num):
            for idx in range(augment_end_idx):
                self.augment_flags.append(True)
                self.audio_paths.append(self.audio_paths[idx])
                self.label_paths.append(self.label_paths[idx])

    def shuffle(self):
        temp = list(zip(self.audio_paths, self.label_paths, self.augment_flags))
        random.shuffle(temp)
        self.audio_paths, self.label_paths, self.augment_flags = zip(*temp)

    def __len__(self):
        return len(self.audio_paths)

    def count(self):
        return len(self.audio_paths)


def split_dataset(args, audio_paths, label_paths, valid_ratio=0.05, target_dict=None):
    """
    split into training set and validation set.

    Args:
        valid_ratio: validation set ratio of total dataset
        args (utils.args.Arguments): set of arguments
        audio_paths (list): set of audio path
        label_paths (list): set of label path
        target_dict (dict): dictionary of filename and target

    Returns: train_batch_num, train_dataset_list, valid_dataset
        - **train_batch_num** (int): num of batch for training
        - **train_dataset_list** (list): list of training dataset
        - **valid_dataset** (utils.dataset.BaseDataset): validation dataset
    """
    logger.info("split dataset start !!")

    trainset_list = list()
    train_num = math.ceil(len(audio_paths) * (1 - valid_ratio))
    total_time_step = math.ceil(len(audio_paths) / args.batch_size)
    valid_time_step = math.ceil(total_time_step * valid_ratio)
    train_time_step = total_time_step - valid_time_step

    if args.use_augment:
        train_time_step = int(train_time_step * (1 + args.augment_num))

    train_num_per_worker = math.ceil(train_num / args.worker_num)

    # audio_paths & label_paths shuffled in the same order
    # for seperating train & validation
    data_paths = list(zip(audio_paths, label_paths))
    random.shuffle(data_paths)
    audio_paths, label_paths = zip(*data_paths)

    # seperating the train dataset by the number of workers
    for idx in range(args.worker_num):
        train_begin_idx = train_num_per_worker * idx
        train_end_idx = min(train_num_per_worker * (idx + 1), train_num)

        trainset_list.append(SpectrogramDataset(
            audio_paths=audio_paths[train_begin_idx:train_end_idx],
            label_paths=label_paths[train_begin_idx:train_end_idx],
            sos_id=SOS_token, eos_id=EOS_token,
            target_dict=target_dict,
            use_augment=args.use_augment,
            args=args
        ))

    validset = SpectrogramDataset(
        audio_paths=audio_paths[train_num:],
        label_paths=label_paths[train_num:],
        sos_id=SOS_token, eos_id=EOS_token,
        target_dict=target_dict,
        args=args,
        use_augment=False
    )

    save_pickle(trainset_list, './data/pickle/trainset_list')
    save_pickle(validset, './data/pickle/validset')

    logger.info("split dataset complete !!")
    return train_time_step, trainset_list, validset